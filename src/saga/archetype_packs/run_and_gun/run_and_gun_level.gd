class_name SagaRunAndGunLevel
extends Node2D

var state := "playing"
var player: SagaRunAndGunPlayer
var enemies: Array[Node] = []
var hazards: Array[Node] = []
var pickups: Array[Node] = []
var weapon_pickups: Array[Node] = []
var wave_definitions: Array = []
var active_wave_enemies: Array[Node] = []
var active_wave_definition: Dictionary = {}
var pending_wave_index := 0
var completed_waves := 0
var boss: SagaRunAndGunBoss
var checkpoint: SagaRunAndGunCheckpoint
var player_sprite: Sprite2D
var status_label: Label
var objective_label: Label
var upgrade_layer: CanvasLayer
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
	CampaignProfile.begin_level(int(_definition.get("level_index", 0)))
	_build_background()
	_build_world()
	_build_player()
	_build_checkpoint()
	_build_hazards_and_pickups()
	_build_weapon_pickups()
	_prepare_waves()
	_build_enemies()
	_build_hud()

func _process(_delta: float) -> void:
	_maybe_trigger_wave()
	var route_clear := kills >= total_enemies and completed_waves >= wave_definitions.size()
	if is_instance_valid(boss):
		boss.set_shielded(not route_clear)
	if not is_instance_valid(status_label):
		return
	var weapon := player.weapon_snapshot()
	var ammo_text := "INF" if int(weapon.get("ammo", -1)) < 0 else str(weapon.get("ammo", 0))
	var campaign := CampaignProfile.snapshot()
	status_label.text = "HP %d/%d   %s %s   CREDITS %d   CHECKPOINT %s" % [
		player.health, player.max_health, str(weapon.get("id", "pulse")).to_upper(), ammo_text,
		int(campaign.get("currency", 0)),
		"ACTIVE" if checkpoint_active else "--"
	]
	objective_label.text = "TARGETS %d/%d   WAVES %d/%d   BOSS %s %d/%d" % [
		kills, total_enemies, completed_waves, wave_definitions.size(),
		"SHIELDED" if not route_clear else "OPEN",
		boss.health if is_instance_valid(boss) else 0,
		boss.max_health if is_instance_valid(boss) else int(_definition.get("boss_health", 1))
	]
	if state == "over" and Input.is_action_just_pressed("ui_accept"):
		restart_from_checkpoint()

func _asset(name: String) -> String:
	return str((_definition.get("assets", {}) as Dictionary).get(name, ""))

func _encounter_plan() -> Dictionary:
	return _definition.get("encounter_plan", {}) as Dictionary

func _combat_plan() -> Dictionary:
	return _encounter_plan().get("combat_plan", {}) as Dictionary

func _progression_plan() -> Dictionary:
	return _definition.get("progression", {}) as Dictionary

func _build_background() -> void:
	var path := _asset("background")
	if path == "":
		RenderingServer.set_default_clear_color(Color("101827"))
		_build_fallback_background()
		return
	var texture := load(path) as Texture2D
	if texture == null:
		return
	var size := texture.get_size()
	var world_width := float(_definition.get("world_width", 2000.0))
	var tile_count := ceili(world_width / 1024.0) + 1
	for index in tile_count:
		var sprite := Sprite2D.new()
		sprite.texture = texture
		sprite.centered = true
		sprite.position = Vector2(512.0 + index * 1024.0, 288)
		sprite.scale = Vector2(1025.0 / maxf(size.x, 1.0), 576.0 / maxf(size.y, 1.0))
		sprite.z_index = -100
		add_child(sprite)

func _build_fallback_background() -> void:
	var width := float(_definition.get("world_width", 2000.0))
	var sky := Polygon2D.new()
	sky.polygon = PackedVector2Array([Vector2(0, 0), Vector2(width, 0), Vector2(width, 576), Vector2(0, 576)])
	sky.color = Color("101827")
	sky.z_index = -110
	add_child(sky)
	for layer in 3:
		var ridge := Polygon2D.new()
		var points := PackedVector2Array([Vector2(0, 576)])
		var base_y := 360.0 + layer * 58.0
		for x in range(0, int(width) + 180, 180):
			points.append(Vector2(x, base_y - float((x / 180 + layer) % 3) * 34.0))
		points.append(Vector2(width, 576))
		ridge.polygon = points
		ridge.color = [Color("18283a"), Color("1d3145"), Color("22394d")][layer]
		ridge.z_index = -105 + layer
		add_child(ridge)

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
	if size.y <= 30.0:
		visual.polygon = PackedVector2Array([
			Vector2(-size.x / 2.0, -size.y / 2.0), Vector2(size.x / 2.0, -size.y / 2.0),
			Vector2(size.x / 2.0, -size.y / 2.0 + 8.0), Vector2(-size.x / 2.0, -size.y / 2.0 + 8.0)
		])
	else:
		visual.polygon = PackedVector2Array([
			Vector2(-size.x / 2.0, -size.y / 2.0), Vector2(size.x / 2.0, -size.y / 2.0),
			Vector2(size.x / 2.0, size.y / 2.0), Vector2(-size.x / 2.0, size.y / 2.0)
		])
	visual.color = color.darkened(0.22)
	body.add_child(visual)
	var top_trim := Polygon2D.new()
	top_trim.polygon = PackedVector2Array([
		Vector2(-size.x / 2.0, -size.y / 2.0), Vector2(size.x / 2.0, -size.y / 2.0),
		Vector2(size.x / 2.0, -size.y / 2.0 + 5.0), Vector2(-size.x / 2.0, -size.y / 2.0 + 5.0)
	])
	top_trim.color = Color("f3a33a")
	body.add_child(top_trim)
	var lower_trim := Line2D.new()
	lower_trim.points = PackedVector2Array([
		Vector2(-size.x / 2.0, size.y / 2.0 - 3.0), Vector2(size.x / 2.0, size.y / 2.0 - 3.0)
	])
	lower_trim.width = 3.0
	lower_trim.default_color = Color("6d8294") if size.y <= 30.0 else Color("132235")
	body.add_child(lower_trim)
	for panel_x in range(int(-size.x / 2.0) + 48, int(size.x / 2.0), 96):
		var seam := Line2D.new()
		if size.y <= 30.0:
			seam.points = PackedVector2Array([
				Vector2(panel_x - 48.0, -size.y / 2.0 + 7.0),
				Vector2(panel_x, size.y / 2.0 - 3.0),
				Vector2(panel_x + 48.0, -size.y / 2.0 + 7.0)
			])
		else:
			seam.points = PackedVector2Array([
				Vector2(panel_x, -size.y / 2.0 + 7.0), Vector2(panel_x, size.y / 2.0 - 5.0)
			])
		seam.width = 2.0
		seam.default_color = Color("536f85") if size.y <= 30.0 else Color(0.08, 0.16, 0.24, 0.72)
		body.add_child(seam)
	if size.y <= 30.0:
		for support_x in [-size.x * 0.32, size.x * 0.32]:
			var support := Polygon2D.new()
			support.polygon = PackedVector2Array([
				Vector2(support_x - 9.0, size.y / 2.0), Vector2(support_x + 9.0, size.y / 2.0),
				Vector2(support_x + 4.0, size.y / 2.0 + 28.0), Vector2(support_x - 4.0, size.y / 2.0 + 28.0)
			])
			support.color = Color("172a3e")
			body.add_child(support)
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
		"world_limit": _definition.get("world_width", 2000.0),
	})
	CampaignProfile.apply_to_player(player)
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

func _build_weapon_pickups() -> void:
	for item_value in _combat_plan().get("weapon_pickups", []) as Array:
		var item := item_value as Dictionary
		var pickup := SagaRunAndGunWeaponPickup.new()
		pickup.position = Vector2(float(item.get("x", 620.0)), float(item.get("y", 465.0)))
		add_child(pickup)
		pickup.configure(item)
		weapon_pickups.append(pickup)

func _prepare_waves() -> void:
	wave_definitions = _combat_plan().get("waves", []) as Array
	var wave_members := 0
	for wave_value in wave_definitions:
		var wave := wave_value as Dictionary
		wave_members += (wave.get("members", []) as Array).size()
	total_enemies = (_encounter_plan().get("enemy_spawns", []) as Array).size() + wave_members

func _role_color(role: String) -> Color:
	if role == "bruiser":
		return Color("ffad5c")
	if role == "hunter":
		return Color("ef6bff")
	if role == "turret":
		return Color("ffdf6b")
	if role == "flyer":
		return Color("6ba8ff")
	return Color("ff786b")

func _spawn_enemy(spawn: Dictionary, wave_member: bool = false) -> SagaRunAndGunEnemy:
	var role := str(spawn.get("role", "scout"))
	var enemy := SagaRunAndGunEnemy.new()
	enemy.position = Vector2(float(spawn.get("x", 420.0)), float(spawn.get("y", 500.0)))
	add_child(enemy)
	var role_size := Vector2(64, 64) if role == "bruiser" else (Vector2(48, 42) if role == "flyer" else Vector2(52, 52))
	var role_asset := _asset("enemy_%s" % role)
	if role_asset == "":
		role_asset = _asset("enemy")
	enemy.actor_sprite = _make_sprite(enemy, role_asset, _role_color(role), role_size)
	enemy.configure({
		"target": player,
		"role": role,
		"move_speed": float(_definition.get("enemy_speed", 90.0)),
		"health": int(_definition.get("enemy_health", 2)),
		"projectile_speed": float(_definition.get("projectile_speed", 700.0)) * 0.62,
		"patrol_distance": 105.0,
	})
	enemy.died.connect(_on_enemy_died)
	enemies.append(enemy)
	if wave_member:
		active_wave_enemies.append(enemy)
	return enemy

func _spawn_wave(wave: Dictionary) -> void:
	active_wave_definition = wave
	active_wave_enemies.clear()
	player.set_arena_lock(float(wave.get("lock_start", 24.0)), float(wave.get("lock_end", _definition.get("world_width", 2000.0))))
	var safe_gap := 210.0
	var lock_start := float(wave.get("lock_start", 24.0))
	var lock_end := float(wave.get("lock_end", _definition.get("world_width", 2000.0)))
	for member_value in wave.get("members", []) as Array:
		var member := (member_value as Dictionary).duplicate()
		var spawn_x := float(member.get("x", lock_end - 100.0))
		if absf(spawn_x - player.global_position.x) < safe_gap:
			spawn_x = clampf(player.global_position.x + safe_gap, lock_start + 70.0, lock_end - 70.0)
		member["x"] = spawn_x
		_spawn_enemy(member, true)

func _maybe_trigger_wave(force: bool = false) -> void:
	if state != "playing" or not active_wave_definition.is_empty() or pending_wave_index >= wave_definitions.size():
		return
	var wave := wave_definitions[pending_wave_index] as Dictionary
	if not force and player.global_position.x < float(wave.get("trigger_x", 99999.0)):
		return
	pending_wave_index += 1
	_spawn_wave(wave)

func _finish_active_wave() -> void:
	if active_wave_definition.is_empty() or not active_wave_enemies.is_empty():
		return
	completed_waves += 1
	active_wave_definition = {}
	player.clear_arena_lock()
	Sfx.play("win")

func _build_enemies() -> void:
	var width := float(_definition.get("world_width", 2000.0))
	var spawns: Array = _encounter_plan().get("enemy_spawns", []) as Array
	for index in spawns.size():
		var spawn := spawns[index] as Dictionary
		_spawn_enemy(spawn)
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
	panel.size = Vector2(670, 76)
	panel.color = Color(0.02, 0.04, 0.08, 0.84)
	canvas.add_child(panel)
	status_label = Label.new()
	status_label.position = Vector2(28, 22)
	status_label.add_theme_font_size_override("font_size", 16)
	canvas.add_child(status_label)
	objective_label = Label.new()
	objective_label.position = Vector2(28, 50)
	objective_label.add_theme_font_size_override("font_size", 15)
	canvas.add_child(objective_label)
	var controls := Label.new()
	controls.position = Vector2(690, 22)
	controls.size = Vector2(320, 48)
	controls.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	controls.add_theme_font_size_override("font_size", 13)
	controls.text = "%s\nARROWS move/jump  ENTER fire  TAB gun" % str(_encounter_plan().get("layout_id", "route")).to_upper()
	canvas.add_child(controls)

func _on_player_died() -> void:
	state = "over"
	status_label.text = "SYSTEM DOWN — ENTER TO RESPAWN"

func _on_enemy_died(enemy: Node) -> void:
	kills += 1
	active_wave_enemies.erase(enemy)
	_finish_active_wave()
	Sfx.play("hit")

func _on_boss_died(_enemy: Node) -> void:
	player.can_control = false
	var progression := _progression_plan()
	CampaignProfile.award_level(
		str(progression.get("reward_id", "level_reward")),
		int(progression.get("currency_reward", 20)),
		int(progression.get("xp_reward", 30))
	)
	Sfx.play("win")
	if bool(_definition.get("has_next_level", false)):
		state = "upgrade"
		objective_label.text = "SECTOR CLEAR — CHOOSE AN UPGRADE"
		_show_upgrade_choices()
	else:
		state = "won"
		objective_label.text = "SECTOR CLEAR"
		_complete_level()

func _complete_level() -> void:
	if not _completion_sent:
		_completion_sent = true
		Game.level_complete()

func _show_upgrade_choices() -> void:
	if is_instance_valid(upgrade_layer):
		upgrade_layer.queue_free()
	upgrade_layer = CanvasLayer.new()
	upgrade_layer.layer = 20
	add_child(upgrade_layer)
	var backdrop := ColorRect.new()
	backdrop.position = Vector2(170, 165)
	backdrop.size = Vector2(684, 235)
	backdrop.color = Color(0.02, 0.03, 0.08, 0.96)
	upgrade_layer.add_child(backdrop)
	var title := Label.new()
	title.position = Vector2(235, 205)
	title.text = "CHOOSE YOUR CAMPAIGN UPGRADE"
	title.add_theme_font_size_override("font_size", 25)
	upgrade_layer.add_child(title)
	var cost := int(_progression_plan().get("upgrade_cost", 10))
	var choices := Label.new()
	choices.position = Vector2(225, 265)
	choices.text = "[1] FIREPOWER  +1 damage\n[2] MOBILITY   +8%% speed\n[3] VITALITY   +2 max health\n\nCost: %d credits" % cost
	choices.add_theme_font_size_override("font_size", 19)
	upgrade_layer.add_child(choices)

func _choose_upgrade(track: String) -> bool:
	if state != "upgrade":
		return false
	var cost := int(_progression_plan().get("upgrade_cost", 10))
	if not CampaignProfile.purchase_upgrade(track, cost):
		return false
	CampaignProfile.apply_to_player(player)
	if is_instance_valid(upgrade_layer):
		upgrade_layer.queue_free()
	state = "won"
	objective_label.text = "%s UPGRADED — DEPLOYING" % track.to_upper()
	_complete_level()
	return true

func _unhandled_input(event: InputEvent) -> void:
	if state != "upgrade" or not event is InputEventKey:
		return
	var key_event := event as InputEventKey
	if not key_event.pressed or key_event.echo:
		return
	if key_event.keycode == KEY_1:
		_choose_upgrade("firepower")
	elif key_event.keycode == KEY_2:
		_choose_upgrade("mobility")
	elif key_event.keycode == KEY_3:
		_choose_upgrade("vitality")

func restart_from_checkpoint() -> void:
	state = "playing"
	player.reset_at_checkpoint()
	CampaignProfile.apply_to_player(player)
	if not active_wave_definition.is_empty():
		var wave := active_wave_definition.duplicate(true)
		for enemy in active_wave_enemies:
			if is_instance_valid(enemy):
				enemy.queue_free()
		active_wave_enemies.clear()
		_spawn_wave(wave)

# Stable QA adapter: the harness exercises real pack state instead of parsing
# game-specific labels or depending on a model-invented node path.
func qa_snapshot() -> Dictionary:
	var plan := _encounter_plan()
	var combat := _combat_plan()
	var weapon := player.weapon_snapshot()
	var campaign := CampaignProfile.snapshot()
	var upgrades := campaign.get("upgrades", {}) as Dictionary
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
		"enemy_role_count": (combat.get("enemy_roles", []) as Array).size(),
		"weapon_id": str(weapon.get("id", "pulse")),
		"weapon_ammo": int(weapon.get("ammo", -1)),
		"weapon_projectiles": int(weapon.get("projectiles", 1)),
		"weapon_damage": int(weapon.get("damage", 1)),
		"weapon_blast_radius": float(weapon.get("blast_radius", 0.0)),
		"weapon_inventory_size": int(weapon.get("inventory_size", 1)),
		"wave_count": wave_definitions.size(),
		"wave_active": not active_wave_definition.is_empty(),
		"wave_active_enemies": active_wave_enemies.size(),
		"completed_waves": completed_waves,
		"threat_budget_limit": int(combat.get("threat_budget_limit", 0)),
		"threat_budget_spent": int(combat.get("threat_budget_spent", 0)),
		"boss_phase": boss.phase if is_instance_valid(boss) else 0,
		"boss_pattern_projectiles": boss.attack_pattern_projectiles() if is_instance_valid(boss) else 0,
		"profile_schema_version": int(campaign.get("schema_version", -1)),
		"campaign_currency": int(campaign.get("currency", 0)),
		"campaign_xp": int(campaign.get("xp", 0)),
		"claimed_rewards": (campaign.get("claimed_rewards", []) as Array).size(),
		"firepower_level": int(upgrades.get("firepower", 0)),
		"mobility_level": int(upgrades.get("mobility", 0)),
		"vitality_level": int(upgrades.get("vitality", 0)),
		"campaign_last_level": int(campaign.get("last_level", -1)),
		"campaign_load_status": str(campaign.get("last_load_status", "")),
	}

func qa_fire() -> void:
	player.fire()

func qa_equip_weapon(weapon_id: String) -> void:
	player.equip_weapon(weapon_id, 12 if weapon_id == "spread" else 5)

func qa_collect_weapon() -> void:
	for pickup in weapon_pickups:
		if is_instance_valid(pickup):
			pickup.collect(player)
			return

func qa_trigger_wave() -> void:
	_maybe_trigger_wave(true)

func qa_clear_wave() -> void:
	for enemy in active_wave_enemies.duplicate():
		if is_instance_valid(enemy):
			enemy.take_damage(enemy.health)

func qa_set_boss_phase(phase: int) -> void:
	if is_instance_valid(boss):
		boss.qa_set_phase(phase)

func qa_progression_reset() -> void:
	CampaignProfile.reset_profile(false)
	CampaignProfile.begin_level(int(_definition.get("level_index", 0)))
	CampaignProfile.apply_to_player(player)

func qa_progression_award() -> void:
	var progression := _progression_plan()
	CampaignProfile.award_level(
		str(progression.get("reward_id", "level_reward")),
		int(progression.get("currency_reward", 20)),
		int(progression.get("xp_reward", 30))
	)

func qa_progression_buy(track: String) -> void:
	CampaignProfile.purchase_upgrade(track, int(_progression_plan().get("upgrade_cost", 10)))
	CampaignProfile.apply_to_player(player)

func qa_progression_save() -> void:
	CampaignProfile.save_profile()

func qa_progression_zero_memory() -> void:
	CampaignProfile.qa_zero_memory()

func qa_progression_load() -> void:
	CampaignProfile.load_profile()
	CampaignProfile.apply_to_player(player)

func qa_progression_begin_next_level() -> void:
	CampaignProfile.begin_level(int(_definition.get("level_index", 0)) + 1)

func qa_progression_corrupt() -> void:
	CampaignProfile.qa_corrupt_save()

func qa_select_upgrade(track: String) -> void:
	_choose_upgrade(track)

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
		boss.qa_force_damage(boss.health)
