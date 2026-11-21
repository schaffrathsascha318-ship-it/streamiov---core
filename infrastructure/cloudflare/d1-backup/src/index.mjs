import { WorkflowEntrypoint } from "cloudflare:workers";
import { runD1Backup } from "./backup-manager.mjs";

export class D1BackupWorkflow extends WorkflowEntrypoint {
  async run(event, step) {
    return await step.do("export-d1-to-r2-and-verify", async () => {
      return await runD1Backup(this.env);
    });
  }
}

export default {
  async scheduled(_event, env) {
    const id = `daily-${new Date().toISOString().slice(0, 10)}`;
    try {
      await env.D1_BACKUP_WORKFLOW.create({ id, params: { requested_at: new Date().toISOString() } });
    } catch (error) {
      // Duplicate schedule delivery is idempotent: an existing instance for
      // this UTC date means the scheduled backup was already enqueued.
      if (!/already exists|duplicate/i.test(String(error?.message || error))) throw error;
    }
  }
};
