class_name SagaRunAndGunLevel
extends Node2D

var state := "playing"
var player: SagaRunAndGunPlayer
var enemies: Array[Node] = []
var hazards: Array[Node] = []
var pickups: Array[Node] = []
var boss: SagaRunAndGunBoss
var checkpoint: SagaRunAndGunCheckpoint
var player_sprite: Sprite2D
var status_label: Label
var objective_label: Label
var kills := 0
var total_enemies := 0
var checkpoint_active := false
var _completion_sent := false
var _definition: Dictionary

func level_definition() -> Dictionary:
	return {}

func _ready() -> void:
	add_to_group("saga_run_and_gun_level")
	_definition = level_definition()
	_build_background()
	_build_world()
	_build_player()
	_build_checkpoint()
	_build_hazards_and_pickups()
	_build_enemies()
	_build_hud()

func _process(_delta: float) -> void:
	if not is_instance_valid(status_label):
		return
	status_label.text = "HP %d/%d   CHECKPOINT %s" % [
		player.health, player.max_health, "ACTIVE" if checkpoint_active else "--"
	]
	objective_label.text = "TARGETS %d/%d   BOSS %d/%d" % [
		kills, total_enemies, boss.health if is_instance_valid(boss) else 0,
		boss.max_health if is_instance_valid(boss) else int(_definition.get("boss_health", 1))
	]
	if state == "over" and Input.is_action_just_pressed("ui_accept"):
		restart_from_checkpoint()

func _asset(name: String) -> String:
	return str((_definition.get("assets", {}) as Dictionary).get(name, ""))

func _encounter_plan() -> Dictionary:
	return _definition.get("encounter_plan", {}) as Dictionary

func _build_background() -> void:
	var path := _asset("background")
	if path == "":
		RenderingServer.set_default_clear_color(Color("101827"))
		return
	var texture := load(path) as Texture2D
	if texture == null:
		return
	var sprite := Sprite2D.new()
	sprite.texture = texture
	sprite.centered = true
	sprite.position = Vector2(512, 288)
	var size := texture.get_size()
	sprite.scale = Vector2(1024.0 / maxf(size.x, 1.0), 576.0 / maxf(size.y, 1.0))
	sprite.z_index = -100
	add_child(sprite)

func _solid_rect(position: Vector2, size: Vector2, color: Color) -> StaticBody2D:
	var body := StaticBody2D.new()
	body.position = position
	body.collision_layer = 1
	body.collision_mask = 1 | 2
	var collision := CollisionShape2D.new()
	var rectangle := RectangleShape2D.new()
	rectangle.size = size
	collision.shape = rectangle
	body.add_child(collision)
	var visual := Polygon2D.new()
	visual.polygon = PackedVector2Array([
		Vector2(-size.x / 2.0, -size.y / 2.0), Vector2(size.x / 2.0, -size.y / 2.0),
		Vector2(size.x / 2.0, size.y / 2.0), Vector2(-size.x / 2.0, size.y / 2.0)
	])
	visual.color = color
	body.add_child(visual)
	add_child(body)
	return body

func _build_world() -> void:
	var width := float(_definition.get("world_width", 2000.0))
	_solid_rect(Vector2(width / 2.0, 552), Vector2(width, 48), Color("263a4f"))
	var platforms: Array = _encounter_plan().get("platforms", []) as Array
	for item_value in platforms:
		var item := item_value as Dictionary
		_solid_rect(
			Vector2(float(item.get("x", 400.0)), float(item.get("y", 420.0))),
			Vector2(float(item.get("width", 220.0)), float(item.get("height", 22.0))),
			Color("36536b")
		)

func _make_sprite(parent: Node2D, path: String, color: Color, size: Vector2) -> Sprite2D:
	var sprite := Sprite2D.new()
	var texture: Texture2D = null
	if path != "":
		texture = load(path) as Texture2D
	if texture != null:
		sprite.texture = texture
		var texture_size := texture.get_size()
		sprite.scale = Vector2(size.x / maxf(texture_size.x, 1.0), size.y / maxf(texture_size.y, 1.0))
	else:
		var image := Image.create(2, 2, false, Image.FORMAT_RGBA8)
		image.fill(color)
		sprite.texture = ImageTexture.create_from_image(image)
		sprite.scale = size / 2.0
	parent.add_child(sprite)
	return sprite

func _build_player() -> void:
	player = SagaRunAndGunPlayer.new()
	player.position = Vector2(110, 500)
	add_child(player)
	player_sprite = _make_sprite(player, _asset("hero"), Color("5ee8ff"), Vector2(58, 58))
	player.player_sprite = player_sprite
	var walk: Texture2D = player_sprite.texture
	if _asset("hero_walk") != "":
		walk = load(_asset("hero_walk")) as Texture2D
	Anim.set_poses(player_sprite, player_sprite.texture, walk)
	player.configure({
		"move_speed": _definition.get("move_speed", 250.0),
		"projectile_speed": _definition.get("projectile_speed", 700.0),
		"health": _definition.get("player_health", 5),
	})
	player.died.connect(_on_player_died)
	var camera := Camera2D.new()
	camera.position = Vector2(180, -80)
	camera.position_smoothing_enabled = true
	camera.position_smoothing_speed = 7.0
	camera.limit_left = 0
	camera.limit_right = int(_definition.get("world_width", 2000.0))
	camera.limit_top = 0
	camera.limit_bottom = 576
	player.add_child(camera)

func _build_checkpoint() -> void:
	checkpoint = SagaRunAndGunCheckpoint.new()
	var checkpoint_x := float(_encounter_plan().get(
		"checkpoint_x", float(_definition.get("world_width", 2000.0)) * 0.52
	))
	checkpoint.position = Vector2(checkpoint_x, 500)
	add_child(checkpoint)
	checkpoint.checkpoint_sprite = _make_sprite(
		checkpoint, _asset("checkpoint"), Color("ffd86b"), Vector2(42, 64)
	)
	checkpoint.activated.connect(func(_node): checkpoint_active = true)

func _build_hazards_and_pickups() -> void:
	for item_value in _encounter_plan().get("hazards", []) as Array:
		var item := item_value as Dictionary
		var hazard := SagaRunAndGunHazard.new()
		hazard.position = Vector2(float(item.get("x", 700.0)), float(item.get("y", 516.0)))
		add_child(hazard)
		hazard.configure(item)
		hazards.append(hazard)
	for item_value in _encounter_plan().get("pickups", []) as Array:
		var item := item_value as Dictionary
		var pickup := SagaRunAndGunPickup.new()
		pickup.position = Vector2(float(item.get("x", 900.0)), float(item.get("y", 465.0)))
		add_child(pickup)
		pickup.configure(item)
		pickups.append(pickup)

func _build_enemies() -> void:
	var width := float(_definition.get("world_width", 2000.0))
	var spawns: Array = _encounter_plan().get("enemy_spawns", []) as Array
	total_enemies = spawns.size()
	for index in total_enemies:
		var spawn := spawns[index] as Dictionary
		var role := str(spawn.get("role", "scout"))
		var speed_scale := 1.35 if role == "scout" else (0.72 if role == "bruiser" else 1.0)
		var health_bonus := 2 if role == "bruiser" else (1 if role == "hunter" else 0)
		var enemy := SagaRunAndGunEnemy.new()
		enemy.position = Vector2(float(spawn.get("x", 420.0)), float(spawn.get("y", 500.0)))
		add_child(enemy)
		var role_color := Color("ff786b") if role == "scout" else (Color("ffad5c") if role == "bruiser" else Color("ef6bff"))
		var role_size := Vector2(64, 64) if role == "bruiser" else Vector2(52, 52)
		enemy.actor_sprite = _make_sprite(enemy, _asset("enemy"), role_color, role_size)
		enemy.configure({
			"target": player,
			"move_speed": float(_definition.get("enemy_speed", 90.0)) * speed_scale,
			"health": int(_definition.get("enemy_health", 2)) + health_bonus,
			"patrol_distance": 90.0 + index * 12.0,
		})
		enemy.died.connect(_on_enemy_died)
		enemies.append(enemy)
	boss = SagaRunAndGunBoss.new()
	var boss_arena := _encounter_plan().get("boss_arena", {}) as Dictionary
	boss.position = Vector2(float(boss_arena.get("spawn_x", width - 180.0)), 495)
	add_child(boss)
	boss.actor_sprite = _make_sprite(boss, _asset("boss"), Color("c55cff"), Vector2(86, 86))
	boss.configure({
		"target": player,
		"move_speed": float(_definition.get("enemy_speed", 90.0)) * 0.72,
		"health": _definition.get("boss_health", 16),
		"projectile_speed": float(_definition.get("projectile_speed", 700.0)) * 0.65,
	})
	boss.died.connect(_on_boss_died)

func _build_hud() -> void:
	var canvas := CanvasLayer.new()
	add_child(canvas)
	var panel := ColorRect.new()
	panel.position = Vector2(14, 12)
	panel.size = Vector2(620, 76)
	panel.color = Color(0.02, 0.04, 0.08, 0.84)
	canvas.add_child(panel)
	status_label = Label.new()
	status_label.position = Vector2(28, 22)
	status_label.add_theme_font_size_override("font_size", 18)
	canvas.add_child(status_label)
	objective_label = Label.new()
	objective_label.position = Vector2(28, 50)
	objective_label.add_theme_font_size_override("font_size", 17)
	canvas.add_child(objective_label)
	var controls := Label.new()
	controls.position = Vector2(700, 22)
	controls.text = "%s   ARROWS move/jump   ENTER fire" % str(_encounter_plan().get("layout_id", "route")).to_upper()
	canvas.add_child(controls)

func _on_player_died() -> void:
	state = "over"
	status_label.text = "SYSTEM DOWN — ENTER TO RESPAWN"

func _on_enemy_died(_enemy: Node) -> void:
	kills += 1
	Sfx.play("hit")

func _on_boss_died(_enemy: Node) -> void:
	state = "won"
	player.can_control = false
	objective_label.text = "SECTOR CLEAR"
	Sfx.play("win")
	if not _completion_sent:
		_completion_sent = true
		Game.level_complete()

func restart_from_checkpoint() -> void:
	state = "playing"
	player.reset_at_checkpoint()

# Stable QA adapter: the harness exercises real pack state instead of parsing
# game-specific labels or depending on a model-invented node path.
func qa_snapshot() -> Dictionary:
	var plan := _encounter_plan()
	var roles := {}
	for spawn_value in plan.get("enemy_spawns", []) as Array:
		var spawn := spawn_value as Dictionary
		roles[str(spawn.get("role", "unknown"))] = true
	return {
		"state": state,
		"player_health": player.health,
		"player_max_health": player.max_health,
		"player_position": player.global_position,
		"spawn_point": player.spawn_point,
		"projectiles": get_tree().get_nodes_in_group("run_and_gun_projectiles").size(),
		"enemy_count": get_tree().get_nodes_in_group("run_and_gun_enemies").size(),
		"kills": kills,
		"boss_health": boss.health if is_instance_valid(boss) else 0,
		"boss_max_health": boss.max_health if is_instance_valid(boss) else int(_definition.get("boss_health", 1)),
		"checkpoint_active": checkpoint_active,
		"layout_id": str(plan.get("layout_id", "")),
		"platform_count": (plan.get("platforms", []) as Array).size(),
		"encounter_count": (plan.get("encounter_beats", []) as Array).size(),
		"hazard_count": (plan.get("hazards", []) as Array).size(),
		"pickup_count": (plan.get("pickups", []) as Array).size(),
		"enemy_role_count": roles.size(),
	}

func qa_fire() -> void:
	player.fire()

func qa_activate_checkpoint() -> void:
	checkpoint.activate(player)

func qa_damage_player(amount: int) -> void:
	player.take_damage(amount)

func qa_restart() -> void:
	restart_from_checkpoint()

func qa_defeat_enemy() -> void:
	for enemy in enemies:
		if is_instance_valid(enemy):
			enemy.take_damage(enemy.health)
			return

func qa_defeat_boss() -> void:
	if is_instance_valid(boss):
		boss.take_damage(boss.health)
