extends Node2D

const CYAN := Color("#42e8ff")
const MINT := Color("#74ffd1")
const VIOLET := Color("#9b86ff")
const RED := Color("#ff6488")
const WHITE := Color("#f4f7ff")
const MUTED := Color("#aebbd0")
const BG := Color("#080b12")

var game_id := ""
var title := ""
var running := false
var score := 0
var lives := 3
var level := 1
var elapsed := 0.0
var spawn_clock := 0.0
var shot_clock := 0.0
var player_x := 0.5
var pointer_down := false
var pointer_x := 0.5
var entities: Array = []
var bullets: Array = []
var stars: Array = []
var sequence: Array[int] = []
var sequence_step := 0
var sequence_showing := false
var sequence_clock := 0.0
var sequence_flash := -1
var pipe_turns: Array[int] = []
var puzzle_level := 1
var message := "Tippe oder drücke Enter zum Starten."
var rng := RandomNumberGenerator.new()

func _ready() -> void:
	game_id = str(ProjectSettings.get_setting("streamiov/game_id", "neon-relay"))
	title = str(ProjectSettings.get_setting("application/config/name", "StreamioV Game"))
	rng.randomize()
	for i in range(90):
		stars.append(Vector2(rng.randf(), rng.randf()))
	set_process(true)
	queue_redraw()

func _process(delta: float) -> void:
	if not running:
		queue_redraw()
		return
	elapsed += delta
	if game_id == "echo-grid":
		_process_echo(delta)
	elif game_id == "signal-weave":
		pass
	else:
		_process_arcade(delta)
	queue_redraw()

func _process_arcade(delta: float) -> void:
	var direction := 0.0
	if Input.is_key_pressed(KEY_LEFT) or Input.is_key_pressed(KEY_A):
		direction -= 1.0
	if Input.is_key_pressed(KEY_RIGHT) or Input.is_key_pressed(KEY_D):
		direction += 1.0
	player_x = clampf(player_x + direction * delta * 0.85, 0.04, 0.96)
	if pointer_down:
		player_x = lerpf(player_x, pointer_x, minf(1.0, delta * 12.0))
	spawn_clock -= delta
	shot_clock -= delta
	var shooter := game_id in ["pulse-defender", "star-defender"]
	if shooter and (Input.is_key_pressed(KEY_SPACE) or pointer_down) and shot_clock <= 0.0:
		bullets.append({"x": player_x, "y": 0.84, "speed": 1.2})
		shot_clock = 0.20
	if spawn_clock <= 0.0:
		var good := game_id == "neon-relay" and rng.randf() < 0.68
		entities.append({"x": rng.randf_range(0.05, 0.95), "y": -0.04, "good": good, "speed": rng.randf_range(0.20, 0.36) + float(level) * 0.018})
		spawn_clock = maxf(0.22, 0.72 - float(level) * 0.025)
	for i in range(entities.size() - 1, -1, -1):
		var item: Dictionary = entities[i]
		item.y = float(item.y) + float(item.speed) * delta
		entities[i] = item
		if game_id == "neon-relay":
			if Vector2(float(item.x), float(item.y)).distance_to(Vector2(player_x, 0.84)) < 0.065:
				if bool(item.good):
					score += 10
				else:
					lives -= 1
				entities.remove_at(i)
				continue
		elif float(item.y) > 0.88:
			lives -= 1
			entities.remove_at(i)
			continue
		if float(item.y) > 1.08:
			entities.remove_at(i)
	for i in range(bullets.size() - 1, -1, -1):
		var bullet: Dictionary = bullets[i]
		bullet.y = float(bullet.y) - float(bullet.speed) * delta
		bullets[i] = bullet
		if float(bullet.y) < 0.0:
			bullets.remove_at(i)
			continue
		for j in range(entities.size() - 1, -1, -1):
			var enemy: Dictionary = entities[j]
			if Vector2(float(enemy.x), float(enemy.y)).distance_to(Vector2(float(bullet.x), float(bullet.y))) < 0.055:
				entities.remove_at(j)
				bullets.remove_at(i)
				score += 10
				break
	level = 1 + int(score / 100)
	if game_id == "neon-relay" and elapsed >= 60.0:
		message = "RUN COMPLETE · Punkte: %d" % score
		running = false
	elif lives <= 0:
		message = "GAME OVER · Punkte: %d" % score
		running = false

func _process_echo(delta: float) -> void:
	if sequence_showing:
		sequence_clock -= delta
		if sequence_clock <= 0.0:
			sequence_step += 1
			if sequence_step >= sequence.size():
				sequence_showing = false
				sequence_step = 0
				sequence_flash = -1
				message = "Deine Runde – wiederhole die Sequenz."
			else:
				sequence_flash = sequence[sequence_step]
				sequence_clock = 0.58
				message = "Merke dir die Felder …"
		else:
			sequence_flash = sequence[sequence_step]

func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if not running and event.keycode in [KEY_ENTER, KEY_SPACE]:
			_start_game()
		elif running and event.keycode == KEY_ESCAPE:
			running = false
			message = "PAUSE · Enter zum Fortsetzen"
		elif not running and event.keycode == KEY_ENTER:
			_start_game()
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if event.pressed:
			_handle_tap(event.position)
			pointer_down = true
			pointer_x = _normalized_x(event.position.x)
		else:
			pointer_down = false
	if event is InputEventMouseMotion and Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
		pointer_x = _normalized_x(event.position.x)
	if event is InputEventScreenTouch:
		if event.pressed:
			_handle_tap(event.position)
			pointer_down = true
			pointer_x = _normalized_x(event.position.x)
		else:
			pointer_down = false
	if event is InputEventScreenDrag:
		pointer_x = _normalized_x(event.position.x)

func _normalized_x(px: float) -> float:
	return clampf(px / maxf(1.0, get_viewport_rect().size.x), 0.04, 0.96)

func _handle_tap(pos: Vector2) -> void:
	if not running:
		_start_game()
		return
	var size := get_viewport_rect().size
	if game_id == "echo-grid":
		var cell_size := minf(size.x * 0.24, size.y * 0.17)
		var gap := 8.0
		var origin := Vector2((size.x - (cell_size * 3.0 + gap * 2.0)) / 2.0, size.y * 0.25)
		var local := pos - origin
		var col := int(local.x / (cell_size + gap))
		var row := int(local.y / (cell_size + gap))
		var within_x := local.x - col * (cell_size + gap)
		var within_y := local.y - row * (cell_size + gap)
		if local.x >= 0.0 and local.y >= 0.0 and col < 3 and row < 3 and within_x <= cell_size and within_y <= cell_size and not sequence_showing:
			_echo_choose(row * 3 + col)
	elif game_id == "signal-weave":
		var cell_size := minf(size.x * 0.145, size.y * 0.115)
		var gap := 5.0
		var origin := Vector2((size.x - (cell_size * 5.0 + gap * 4.0)) / 2.0, size.y * 0.22)
		var local := pos - origin
		var col := int(local.x / (cell_size + gap))
		var row := int(local.y / (cell_size + gap))
		var within_x := local.x - col * (cell_size + gap)
		var within_y := local.y - row * (cell_size + gap)
		if local.x >= 0.0 and local.y >= 0.0 and col < 5 and row < 5 and within_x <= cell_size and within_y <= cell_size:
			var index := row * 5 + col
			pipe_turns[index] = (pipe_turns[index] + 1) % 4
			_check_signal()

func _start_game() -> void:
	running = true
	score = 0
	lives = 3
	level = 1
	elapsed = 0.0
	spawn_clock = 0.2
	shot_clock = 0.0
	player_x = 0.5
	entities.clear()
	bullets.clear()
	sequence.clear()
	sequence_step = 0
	sequence_showing = false
	sequence_flash = -1
	puzzle_level = 1
	pipe_turns.clear()
	message = "Los geht's!"
	if game_id == "echo-grid":
		_echo_next_round()
	elif game_id == "signal-weave":
		_signal_new_level()

func _echo_next_round() -> void:
	sequence.append(rng.randi_range(0, 8))
	sequence_step = 0
	sequence_showing = true
	sequence_clock = 0.65
	sequence_flash = sequence[0]
	message = "Merke dir die Sequenz …"

func _echo_choose(index: int) -> void:
	if index != sequence[sequence_step]:
		running = false
		message = "Nicht ganz! Runde %d · Tippe zum Neustart." % sequence.size()
		return
	sequence_step += 1
	score += 10
	if sequence_step >= sequence.size():
		level = sequence.size() + 1
		message = "Richtig! Nächste Runde …"
		_echo_next_round()

func _signal_new_level() -> void:
	pipe_turns.clear()
	for i in range(25):
		pipe_turns.append(rng.randi_range(0, 3))
	pipe_turns[10] = rng.randi_range(1, 3)
	pipe_turns[11] = rng.randi_range(0, 3)
	pipe_turns[12] = rng.randi_range(0, 3)
	pipe_turns[13] = rng.randi_range(0, 3)
	pipe_turns[14] = rng.randi_range(0, 3)
	message = "Drehe die Leitungen in Reihe 3 waagerecht."

func _check_signal() -> void:
	var solved := true
	for i in range(10, 15):
		if pipe_turns[i] % 2 != 0:
			solved = false
	if solved:
		score += 100
		puzzle_level += 1
		level = puzzle_level
		if puzzle_level > 3:
			running = false
			message = "Alle Signalwege verbunden!"
		else:
			_signal_new_level()

func _draw() -> void:
	var size := get_viewport_rect().size
	draw_rect(Rect2(Vector2.ZERO, size), BG)
	for star in stars:
		draw_circle(Vector2(star.x * size.x, star.y * size.y), 1.5, Color(0.45, 0.58, 0.78, 0.30))
	draw_string(ThemeDB.fallback_font, Vector2(22, 34), "STREAMIOV  ♥  " + title.to_upper(), HORIZONTAL_ALIGNMENT_LEFT, -1, 18, MINT)
	draw_string(ThemeDB.fallback_font, Vector2(22, 64), "PUNKTE  %d     LEBEN  %d     LEVEL  %d" % [score, lives, level], HORIZONTAL_ALIGNMENT_LEFT, -1, 14, WHITE)
	if game_id == "echo-grid":
		_draw_echo(size)
	elif game_id == "signal-weave":
		_draw_signal(size)
	else:
		_draw_arcade(size)
	if not running:
		var panel := Rect2(size.x * 0.12, size.y * 0.39, size.x * 0.76, size.y * 0.24)
		draw_rect(panel, Color("#111a2b"))
		draw_rect(panel, VIOLET, false, 2.0)
		draw_string(ThemeDB.fallback_font, Vector2(panel.position.x + 18, panel.position.y + 42), message, HORIZONTAL_ALIGNMENT_LEFT, panel.size.x - 36, 18, WHITE)
		draw_string(ThemeDB.fallback_font, Vector2(panel.position.x + 18, panel.position.y + 78), "TIPPE / ENTER ZUM STARTEN", HORIZONTAL_ALIGNMENT_LEFT, panel.size.x - 36, 14, CYAN)

func _draw_arcade(size: Vector2) -> void:
	var player := Vector2(player_x * size.x, size.y * 0.84)
	if game_id == "neon-relay":
		draw_colored_polygon(PackedVector2Array([player + Vector2(0,-22), player + Vector2(18,16), player + Vector2(0,9), player + Vector2(-18,16)]), CYAN)
	else:
		draw_colored_polygon(PackedVector2Array([player + Vector2(0,-22), player + Vector2(20,18), player + Vector2(0,10), player + Vector2(-20,18)]), MINT)
	for item in entities:
		var p := Vector2(float(item.x) * size.x, float(item.y) * size.y)
		var color: Color = CYAN if bool(item.good) else RED
		if game_id != "neon-relay":
			color = RED
		draw_circle(p, 12.0, color)
	for bullet in bullets:
		draw_rect(Rect2(Vector2(float(bullet.x) * size.x - 3, float(bullet.y) * size.y - 10), Vector2(6, 18)), CYAN)
	draw_string(ThemeDB.fallback_font, Vector2(22, size.y - 22), "BEWEGEN: A/D ODER PFEILE  ·  FEUERN: LEERTASTE / TOUCH", HORIZONTAL_ALIGNMENT_LEFT, -1, 12, MUTED)

func _draw_echo(size: Vector2) -> void:
	var cell_size := minf(size.x * 0.24, size.y * 0.17)
	var gap := 8.0
	var origin := Vector2((size.x - (cell_size * 3.0 + gap * 2.0)) / 2.0, size.y * 0.25)
	for i in range(9):
		var rect := Rect2(origin + Vector2((i % 3) * (cell_size + gap), int(i / 3) * (cell_size + gap)), Vector2(cell_size, cell_size))
		draw_rect(rect, MINT if i == sequence_flash else Color("#18243a"))
		draw_rect(rect, VIOLET, false, 2.0)
	draw_string(ThemeDB.fallback_font, Vector2(22, size.y - 28), message, HORIZONTAL_ALIGNMENT_CENTER, size.x - 44, 16, WHITE)

func _draw_signal(size: Vector2) -> void:
	var cell := minf(size.x * 0.145, size.y * 0.115)
	var gap := 5.0
	var origin := Vector2((size.x - (cell * 5.0 + gap * 4.0)) / 2.0, size.y * 0.22)
	for i in range(25):
		var x := i % 5
		var y := int(i / 5)
		var rect := Rect2(origin + Vector2(x * (cell + gap), y * (cell + gap)), Vector2(cell, cell))
		draw_rect(rect, Color("#18243a"))
		draw_rect(rect, VIOLET, false, 1.5)
		var center := rect.get_center()
		if i == 10:
			draw_circle(center, cell * 0.18, CYAN)
		elif i == 14:
			draw_circle(center, cell * 0.18, MINT)
		elif i >= 10 and i <= 14:
			var angle := float(pipe_turns[i]) * PI / 2.0
			var end := center + Vector2(cos(angle), sin(angle)) * cell * 0.38
			draw_line(center - (end - center), end, CYAN, 4.0)
	draw_string(ThemeDB.fallback_font, Vector2(22, size.y - 24), message, HORIZONTAL_ALIGNMENT_CENTER, size.x - 44, 14, WHITE)
