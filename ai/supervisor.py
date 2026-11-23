"""
Persistent AI Chief Supervisor

This module implements a bounded, supervised loop that manages mission state,
handles external failures with backoff, and persists state to a versioned
repository file. It is designed to run locally within the GitHub Actions runner
environment.
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any, Dict, List, Optional, TypeVar, Generic

# Constants
STATE_FILE_PATH = "mission-state.json"
VERSION = "1.0.0"
BACKOFF_BASE = 1.0  # seconds
BACKOFF_MAX = 60.0  # seconds
MAX_RETRIES = 3

T = TypeVar("T")


@dataclass
class TaskResult:
    """Result of a single task execution."""
    task_id: str
    status: str  # "pending", "running", "success", "failed", "skipped"
    result: Any = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskResult":
        return cls(**data)


@dataclass
class MissionState:
    """The persistent state of the current mission."""
    mission_id: str
    version: str = VERSION
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Mission Status
    status: str = "initialized"  # "initialized", "running", "paused", "completed", "failed"
    
    # Progress Tracking
    total_tasks: int = 0
    completed_tasks: int = 0
    progress_percentage: float = 0.0
    
    # Task Execution History
    task_history: List[TaskResult] = field(default_factory=list)
    
    # Checkpointing
    current_checkpoint: str = "start"
    next_steps: List[str] = field(default_factory=list)
    
    # Failure Handling
    failure_count: int = 0
    last_error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Convert datetime fields to ISO strings for JSON serialization
        for key in ["created_at", "updated_at", "started_at", "completed_at"]:
            if key in data and data[key] is not None:
                if isinstance(data[key], datetime):
                    data[key] = data[key].isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MissionState":
        # Convert ISO strings back to datetime objects if needed
        for key in ["created_at", "updated_at", "started_at", "completed_at"]:
            if key in data and data[key] is not None:
                if isinstance(data[key], str):
                    # Simple parsing, assumes valid ISO format
                    data[key] = datetime.fromisoformat(data[key])
        return cls(**data)

    def update_progress(self, completed: int, total: int):
        """Update progress percentage based on completed tasks."""
        self.completed_tasks = completed
        self.total_tasks = total
        self.progress_percentage = (completed / total * 100) if total > 0 else 0.0
        self.updated_at = datetime.utcnow().isoformat()

    def add_task_result(self, result: TaskResult):
        """Add a task result to history."""
        self.task_history.append(result)
        self.completed_tasks += 1
        self.update_progress(self.completed_tasks, self.total_tasks)
        self.updated_at = datetime.utcnow().isoformat()


@dataclass
class SupervisorConfig:
    """Configuration for the Supervisor."""
    state_file_path: str = STATE_FILE_PATH
    backoff_base: float = BACKOFF_BASE
    backoff_max: float = BACKOFF_MAX
    max_retries: int = MAX_RETRIES
    auto_resume: bool = True


class Supervisor(Generic[T]):
    """
    The AI Chief Supervisor.
    
    Manages mission state, executes tasks in a bounded loop, handles failures,
    and persists state to a versioned repository file.
    """
    
    def __init__(self, config: Optional[SupervisorConfig] = None):
        self.config = config or SupervisorConfig()
        self.state: Optional[MissionState] = None
        self._load_state()
        
    def _load_state(self):
        """Load the mission state from the repository file."""
        if not os.path.exists(self.config.state_file_path):
            # Initialize new mission state
            self.state = MissionState(
                mission_id=str(uuid.uuid4()),
                status="initialized",
                next_steps=["initialize_mission"]
            )
            self._save_state()
            return
        
        try:
            with open(self.config.state_file_path, "r") as f:
                data = json.load(f)
                self.state = MissionState.from_dict(data)
                
            # Validate version compatibility
            if self.state.version != VERSION:
                print(f"Warning: State version control mismatch. Expected {VERSION}, got {self.state.version}")
                # In a real system, we might implement migration logic here
                
            print(f"Loaded mission state: {self.state.mission_id} (Status: {self.state.status})")
        except Exception as e:
            print(f"Error loading state: {e}")
            # Fallback to a new mission state
            self.state = MissionState(
                mission_id=str(uuid.uuid4()),
                status="initialized",
                next_steps=["initialize_mission"]
            )
            self._save_state()

    def _save_state(self):
        """Save the mission state to the repository file."""
        try:
            with open(self.config.state_file_path, "w") as f:
                json.dump(self.state.to_dict(), f, indent=2)
        except Exception as e:
            print(f"Error saving state: {e}")

    def _execute_task(self, task_func: callable, task_id: str, *args, **kwargs) -> TaskResult:
        """
        Execute a single task with error handling and result recording.
        
        Args:
            task_func: The function to execute.
            task_id: Unique identifier for the task.
            *args, **kwargs: Arguments to pass to the task function.
            
        Returns:
            TaskResult: The result of the task execution.
        """
        result = TaskResult(
            task_id=task_id,
            status="running",
            started_at=datetime.utcnow().isoformat()
        )
        
        try:
            # Execute the task
            output = task_func(*args, **kwargs)
            
            # Determine success/failure
            if output is None:
                result.status = "skipped"
            else:
                result.status = "success"
                result.result = output
                
        except Exception as e:
            result.status = "failed"
            result.error = str(e)
            
        finally:
            result.completed_at = datetime.utcnow().isoformat()
            if result.started_at:
                start_dt = datetime.fromisoformat(result.started_at)
                end_dt = datetime.fromisoformat(result.completed_at)
                result.duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
            
            # Record the result
            if self.state:
                self.state.add_task_result(result)
                self._save_state()
                
        return result

    def _backoff(self, attempt: int) -> float:
        """
        Calculate backoff time using exponential backoff with jitter.
        
        Args:
            attempt: The current attempt number (0-indexed).
            
        Returns:
            float: The backoff time in seconds.
        """
        if attempt >= self.config.max_retries:
            return self.config.backoff_max
            
        # Exponential backoff: base * (2 ** attempt)
        backoff = self.config.backoff_base * (2 ** attempt)
        
        # Add jitter to prevent thundering herd
        jitter = backoff * 0.1 * (0.5 - (attempt % 2))  # +/- 10% jitter
        
        return min(backoff + jitter, self.config.backoff_max)

    def _run_supervised_loop(self, tasks: List[callable], task_args_list: List[tuple] = None, task_kwargs_list: List[dict] = None):
        """
        Run a bounded, supervised loop that executes tasks, records results, and updates state.
        
        Args:
            tasks: List of task functions to execute.
            task_args_list: List of argument tuples for each task.
            task_kwargs_list: List of keyword argument dicts for each task.
        """
        if task_args_list is None:
            task_args_list = [()] * len(tasks)
        if task_kwargs_list is None:
            task_kwargs_list = [{}] * len(tasks)
            
        if len(tasks) != len(task_args_list) or len(tasks) != len(task_kwargs_list):
            raise ValueError("Length of tasks, task_args_list, and task_kwargs_list must match.")
            
        # Update total tasks in state
        if self.state:
            self.state.total_tasks = len(tasks)
            self.state.status = "running"
            self.state.current_checkpoint = "loop_start"
            self.state.next_steps = [f"task_{i}" for i in range(len(tasks))]
            self._save_state()
            
        attempt = 0
        while attempt < self.config.max_retries:
            try:
                # Execute tasks sequentially
                for i, (task, args, kwargs) in enumerate(zip(tasks, task_args_list, task_kwargs_list)):
                    if self.state and self.state.status == "paused":
                        print("Mission paused. Waiting for resume...")
                        time.sleep(1)
                        continue
                        
                    if self.state and self.state.status == "completed":
                        print("Mission completed. Exiting loop.")
                        break
                        
                    if self.state and self.state.status == "failed":
                        print("Mission failed. Exiting loop.")
                        break
                        
                    # Execute task
                    result = self._execute_task(task, f"task_{i}", *args, **kwargs)
                    
                    # Check for failure
                    if result.status == "failed":
                        self.state.failure_count += 1
                        self.state.last_error = result.error
                        self._save_state()
                        
                        # Backoff and retry
                        backoff_time = self._backoff(attempt)
                        print(f"Task {i} failed. Backing off for {backoff_time:.2f}s before retrying...")
                        time.sleep(backoff_time)
                        attempt += 1
                        
                        # If we've exhausted retries, mark mission as failed
                        if attempt >= self.config.max_retries:
                            self.state.status = "failed"
                            self.state.last_error = f"Max retries ({self.config.max_retries}) exceeded for task {i}"
                            self._save_state()
                            break
                        
                        # Retry the current task
                        continue
                        
                    # Task succeeded, move to next
                    attempt = 0
                    
                # Check if all tasks completed successfully
                if self.state and self.state.status == "completed":
                    print("All tasks completed successfully.")
                    break
                    
            except Exception as e:
                print(f"Unexpected error in supervised loop: {e}")
                self.state.status = "failed"
                self.state.last_error = str(e)
                self._save_state()
                break

    def run(self, tasks: List[callable], task_args_list: List[tuple] = None, task_kwargs_list: List[dict] = None):
        """
        Public method to run the supervised loop.
        
        Args:
            tasks: List of task functions to execute.
            task_args_list: List of argument tuples for each task.
            task_kwargs_list: List of keyword argument dicts for each task.
        """
        self._run_supervised_loop(tasks, task_args_list, task_kwargs_list)

    def get_state(self) -> Optional[MissionState]:
        """Get the current mission state."""
        return self.state

    def get_status(self) -> str:
        """Get the current mission status."""
        if self.state:
            return self.state.status
        return "unknown"

    def pause(self):
        """Pause the mission."""
        if self.state:
            self.state.status = "paused"
            self._save_state()
            print("Mission paused.")

    def resume(self):
        """Resume the mission."""
        if self.state:
            self.state.status = "running"
            self._save_state()
            print("Mission resumed.")

    def complete(self):
        """Mark the mission as completed."""
        if self.state:
            self.state.status = "completed"
            self._save_state()
            print("Mission completed.")

    def fail(self, error: str):
        """Mark the mission as failed."""
        if self.state:
            self.state.status = "failed"
            self.state.last_error = error
            self._save_state()
            print(f"Mission failed: {error}")


def main():
    """
    Main entry point for the Supervisor.
    Demonstrates usage with sample tasks.
    """
    # Example tasks
    def sample_task_1():
        print("Executing sample task 1...")
        time.sleep(0.5)
        return "Task 1 completed successfully"

    def sample_task_2():
        print("Executing sample task 2...")
        time.sleep(0.5)
        return "Task 2 completed successfully"

    def failing_task():
        print("Executing failing task...")
        time.sleep(0.5)
        raise Exception("Simulated external failure")

    # Create supervisor
    supervisor = Supervisor()
    
    # Run tasks
    supervisor.run([
        sample_task_1,
        sample_task_2,
        failing_task
    ])


if __name__ == "__main__":
    main()
