class_name SagaActionRpgLevel
extends Node2D

var state := "playing"
var player: SagaActionRpgPlayer
var inventory := SagaActionRpgInventory.new()
var enemies: Array[Node] = []
var pickups: Array[Node] = []
var npc: SagaActionRpgNpc
var boss: SagaActionRpgBoss
var room_index := 0
var quest_stage := "collect_sparks"
var dash_unlocked := false
var dialogue_open := false
var dialogue_index := 0
var inventory_open := false
var forge_door_open := false
var checkpoint_data: Dictionary = {}
var cleared_enemies: Array = []
var collected_pickups: Array = []
var discovered_rooms: Array = []
var used_shortcuts: Array = []
var _definition: Dictionary
var _x_latched := false
var _c_latched := false
var hud_label: Label
var quest_label: Label
var dialogue_panel: ColorRect
var dialogue_label: Label
var inventory_panel: ColorRect
var inventory_label: Label
var room_label: Label
var room_decor: Node2D
var room_geometry: Node2D

func level_definition() -> Dictionary:
	return {}

func _ready() -> void:
	add_to_group("saga_action_rpg_level")
	_ensure_input_actions()
	_definition = level_definition()
	RenderingServer.set_default_clear_color(Color("10151d"))
	_build_background()
	_build_room_shell()
	room_geometry = Node2D.new()
	room_geometry.name = "AuthoredRoomGeometry"
	add_child(room_geometry)
	room_decor = Node2D.new()
	room_decor.z_index = -20
	add_child(room_decor)
	_build_player()
	_build_hud()
	_restore_or_begin()
	_load_room(room_index)
	checkpoint_room()
	if "--presentation-capture" in OS.get_cmdline_user_args():
		call_deferred("_prepare_presentation_capture")

func _prepare_presentation_capture() -> void:
	# A compact, deterministic combat vignette for temporal QA. It uses the
	# production enemy, player, damage, animation and feedback code; only the
	# spawn position is staged so sparse video sampling actually sees combat.
	for enemy in enemies:
		if is_instance_valid(enemy):
			enemy.queue_free()
	enemies.clear()
	player.position = Vector2(330, 320)
	player.facing = Vector2.RIGHT
	_spawn_enemy("presentation_sentinel", Vector2(405, 320), "sentinel", 12, _narrative_text("enemy_name", "Enemy") + " Sentinel")

func _process(_delta: float) -> void:
	if not is_instance_valid(player):
		return
	var x_pressed := Input.is_key_pressed(KEY_X) or Input.is_action_pressed("rpg_interact")
	if x_pressed and not _x_latched:
		if dialogue_open:
			advance_dialogue()
		elif room_index == 0 and player.position.distance_to(npc.position) < 95.0:
			begin_dialogue()
	_x_latched = x_pressed
	var c_pressed := Input.is_key_pressed(KEY_C) or Input.is_action_pressed("rpg_inventory")
	if c_pressed and not _c_latched:
		toggle_inventory()
	_c_latched = c_pressed
	if state == "over" and Input.is_action_just_pressed("ui_accept"):
		restart_from_checkpoint()
	if state == "playing" and not dialogue_open and not inventory_open:
		# Transition before the player's collision capsule reaches the invisible
		# boundary wall. The old 985/39 thresholds sat beyond the physical travel
		# limit, leaving players walking forever against the edge.
		if player.position.x >= 970.0:
			transition_exit("east")
		elif player.position.x <= 54.0:
			if room_index == _last_room_index() and is_instance_valid(boss):
				# The forge is a committed boss arena. Letting the west edge
				# transition during a dodge silently unloads the boss and strands
				# the quest in an unwinnable state.
				player.position.x = 60.0
			else:
				transition_exit("west")
		elif player.position.y <= 122.0:
			transition_exit("north")
		elif player.position.y >= 514.0:
			transition_exit("south")
	_update_hud()

func _ensure_input_actions() -> void:
	var bindings := {
		"rpg_attack": KEY_Z,
		"rpg_interact": KEY_X,
		"rpg_inventory": KEY_C,
		"rpg_dash": KEY_SHIFT
	}
	for action in bindings:
		if not InputMap.has_action(action):
			InputMap.add_action(action)
		if InputMap.action_get_events(action).is_empty():
			var event := InputEventKey.new()
			event.physical_keycode = int(bindings[action])
			InputMap.action_add_event(action, event)

func _asset(name: String) -> String:
	return str((_definition.get("assets", {}) as Dictionary).get(name, ""))

func _rooms() -> Array:
	return ((_definition.get("room_plan", {}) as Dictionary).get("rooms", []) as Array)

func _world_graph() -> Dictionary:
	return ((_definition.get("room_plan", {}) as Dictionary).get("world_graph", {}) as Dictionary)

func _room_id(index: int = room_index) -> String:
	var rooms := _rooms()
	if index < 0 or index >= rooms.size():
		return ""
	return str((rooms[index] as Dictionary).get("id", ""))

func _room_index_for_id(room_id: String) -> int:
	for index in range(_rooms().size()):
		if _room_id(index) == room_id:
			return index
	return -1

func _exit_for(room_id: String, direction: String) -> Dictionary:
	for edge_value in (_world_graph().get("edges", []) as Array):
		var edge := edge_value as Dictionary
		if str(edge.get("from", "")) == room_id and str(edge.get("direction", "")) == direction:
			return {
				"edge_id": str(edge.get("id", "")), "target": str(edge.get("to", "")),
				"kind": str(edge.get("kind", "main_route")),
				"requires_quest_stage": str(edge.get("requires_quest_stage", ""))
			}
		if str(edge.get("to", "")) == room_id and str(edge.get("return_direction", "")) == direction:
			return {
				"edge_id": str(edge.get("id", "")), "target": str(edge.get("from", "")),
				"kind": str(edge.get("kind", "main_route")), "requires_quest_stage": ""
			}
	return {}

func _narrative() -> Dictionary:
	return ((_definition.get("room_plan", {}) as Dictionary).get("narrative", {}) as Dictionary)

func _narrative_text(field: String, fallback: String) -> String:
	return str(_narrative().get(field, fallback))

func _quest_cost() -> int:
	return maxi(1, int(((_definition.get("room_plan", {}) as Dictionary).get("quest", {}) as Dictionary).get("spark_cost", 10)))

func _quest_npc_data() -> Dictionary:
	for room_value in _rooms():
		var room := room_value as Dictionary
		if room.get("npc") is Dictionary:
			return room.get("npc") as Dictionary
	return {}

func _item_display_name(item_id: String) -> String:
	for room_value in _rooms():
		for pickup_value in ((room_value as Dictionary).get("pickups", []) as Array):
			var pickup := pickup_value as Dictionary
			if str(pickup.get("id", "")) == item_id:
				return str(pickup.get("display_name", item_id.replace("_", " ").capitalize()))
	return item_id.replace("_", " ").capitalize()

func _room_count() -> int:
	return maxi(1, _rooms().size())

func _last_room_index() -> int:
	return _room_count() - 1

func _attach_asset(node: Node2D, asset_name: String, max_size: float) -> bool:
	var path := _asset(asset_name)
	if path == "":
		return false
	var texture := load(path) as Texture2D
	if texture == null:
		return false
	# Stable-pack silhouettes are safety fallbacks, never part of the authored
	# final composition. Keeping them visible under a real sprite produced the
	# colored squares and diamonds that made otherwise valid art look broken.
	for child in node.get_children():
		if child is Polygon2D and str(child.name) == "FallbackVisual":
			child.visible = false
	var sprite := Sprite2D.new()
	sprite.name = "AuthoredSprite"
	sprite.texture = texture
	sprite.scale = Vector2.ONE * minf(
		max_size / maxf(texture.get_width(), 1),
		max_size / maxf(texture.get_height(), 1)
	)
	sprite.position.y = -6
	sprite.z_index = 2
	node.add_child(sprite)
	return true

func _build_background() -> void:
	var path := _asset("background")
	if path != "":
		var texture := load(path) as Texture2D
		if texture != null:
			var sprite := Sprite2D.new()
			sprite.texture = texture
			sprite.centered = true
			sprite.position = Vector2(512, 288)
			var size := texture.get_size()
			sprite.scale = Vector2(1025.0 / maxf(size.x, 1.0), 577.0 / maxf(size.y, 1.0))
			sprite.modulate = Color(0.65, 0.7, 0.75, 1.0)
			sprite.z_index = -100
			add_child(sprite)
			return
	var fallback := Polygon2D.new()
	fallback.polygon = PackedVector2Array([Vector2(0, 0), Vector2(1024, 0), Vector2(1024, 576), Vector2(0, 576)])
	fallback.color = Color("172431")
	fallback.z_index = -100
	add_child(fallback)

func _wall(position: Vector2, size: Vector2, style := "boundary", parent: Node = null) -> void:
	var wall := StaticBody2D.new()
	wall.position = position
	wall.collision_layer = 1
	wall.collision_mask = 2 | 4
	var collision := CollisionShape2D.new()
	var shape := RectangleShape2D.new()
	shape.size = size
	collision.shape = shape
	wall.add_child(collision)
	var bevel := minf(14.0, minf(size.x, size.y) * 0.28)
	var points := PackedVector2Array([
		Vector2(-size.x / 2 + bevel, -size.y / 2), Vector2(size.x / 2 - bevel, -size.y / 2),
		Vector2(size.x / 2, -size.y / 2 + bevel), Vector2(size.x / 2, size.y / 2 - bevel),
		Vector2(size.x / 2 - bevel, size.y / 2), Vector2(-size.x / 2 + bevel, size.y / 2),
		Vector2(-size.x / 2, size.y / 2 - bevel), Vector2(-size.x / 2, -size.y / 2 + bevel)
	])
	var visual := Polygon2D.new()
	visual.polygon = points
	var colors := {
		"boundary": Color("182a35"), "ember_slab": Color("744632"),
		"rune_pillar": Color("4e5d78"), "moon_pillar": Color("414b70"),
		"moon_slab": Color("526283"), "verdant_slab": Color("3f6858"),
		"verdant_pillar": Color("315a4b"), "iron_tooth": Color("70443d"),
		"boss_pillar": Color("773e45")
	}
	var base_color: Color = colors.get(style, Color("384b59"))
	visual.color = Color(base_color, 0.48 if style != "boundary" else 0.88)
	wall.add_child(visual)
	var outline := Line2D.new()
	outline.points = points
	outline.add_point(points[0])
	outline.width = 2.0
	outline.default_color = Color(base_color.lightened(0.34), 0.82)
	wall.add_child(outline)
	if style != "boundary":
		var sigil := Line2D.new()
		sigil.points = PackedVector2Array([Vector2(-size.x * 0.22, 0), Vector2(0, -size.y * 0.24), Vector2(size.x * 0.22, 0), Vector2(0, size.y * 0.24), Vector2(-size.x * 0.22, 0)])
		sigil.width = 2.0
		sigil.default_color = Color(1.0, 0.74, 0.35, 0.72)
		wall.add_child(sigil)
	(parent if parent != null else self).add_child(wall)

func _build_room_shell() -> void:
	_wall(Vector2(512, 76), Vector2(1024, 28))
	_wall(Vector2(512, 562), Vector2(1024, 28))
	_wall(Vector2(12, 288), Vector2(24, 576))
	_wall(Vector2(1012, 288), Vector2(24, 576))

func _vector_from(value, fallback: Vector2) -> Vector2:
	if value is Array and value.size() >= 2:
		return Vector2(float(value[0]), float(value[1]))
	return fallback

func _build_room_geometry(room_data: Dictionary) -> void:
	for child in room_geometry.get_children():
		child.queue_free()
	for obstacle_value in (room_data.get("obstacles", []) as Array):
		var obstacle := obstacle_value as Dictionary
		_wall(
			_vector_from(obstacle.get("position", []), Vector2(512, 288)),
			_vector_from(obstacle.get("size", []), Vector2(88, 38)),
			str(obstacle.get("style", "ember_slab")),
			room_geometry
		)

func _build_player() -> void:
	player = SagaActionRpgPlayer.new()
	player.move_speed = float(_definition.get("move_speed", 180.0))
	player.max_health = int(_definition.get("player_health", 5))
	player.health = player.max_health
	player.position = Vector2(150, 320)
	player.swing_requested.connect(_on_player_swing)
	player.defeated.connect(_on_player_defeated)
	add_child(player)
	player.set_authored_visual(_asset("hero"), _asset("hero_walk"), 58.0)

func _build_hud() -> void:
	var layer := CanvasLayer.new()
	layer.name = "HUD"
	add_child(layer)
	var backing := ColorRect.new()
	backing.position = Vector2(12, 10)
	backing.size = Vector2(1000, 62)
	backing.color = Color(0.025, 0.045, 0.065, 0.92)
	layer.add_child(backing)
	hud_label = Label.new()
	hud_label.name = "HUDStatus"
	hud_label.position = Vector2(26, 18)
	hud_label.add_theme_font_size_override("font_size", 17)
	layer.add_child(hud_label)
	quest_label = Label.new()
	quest_label.position = Vector2(26, 43)
	quest_label.add_theme_color_override("font_color", Color("f5bc65"))
	layer.add_child(quest_label)
	room_label = Label.new()
	room_label.position = Vector2(825, 20)
	room_label.add_theme_font_size_override("font_size", 15)
	layer.add_child(room_label)
	dialogue_panel = ColorRect.new()
	dialogue_panel.position = Vector2(110, 400)
	dialogue_panel.size = Vector2(804, 128)
	dialogue_panel.color = Color(0.04, 0.03, 0.06, 0.96)
	dialogue_panel.visible = false
	layer.add_child(dialogue_panel)
	dialogue_label = Label.new()
	dialogue_label.position = Vector2(22, 17)
	dialogue_label.size = Vector2(760, 92)
	dialogue_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	dialogue_panel.add_child(dialogue_label)
	inventory_panel = ColorRect.new()
	inventory_panel.position = Vector2(690, 92)
	inventory_panel.size = Vector2(310, 250)
	inventory_panel.color = Color(0.035, 0.055, 0.075, 0.97)
	inventory_panel.visible = false
	layer.add_child(inventory_panel)
	inventory_label = Label.new()
	inventory_label.position = Vector2(18, 16)
	inventory_label.size = Vector2(274, 220)
	inventory_panel.add_child(inventory_label)
	_update_hud()

func _restore_or_begin() -> void:
	var profile := ActionRpgProfile.snapshot()
	room_index = clampi(int(profile.get("room_index", 0)), 0, _last_room_index())
	player.health = clampi(int(profile.get("hero_hp", player.max_health)), 1, player.max_health)
	inventory.restore({"sparks": profile.get("sparks", 0), "items": profile.get("items", {})})
	quest_stage = str(profile.get("quest_stage", "collect_sparks"))
	dash_unlocked = bool(profile.get("dash_unlocked", false))
	forge_door_open = quest_stage in ["forge_open", "complete"]
	player.dash_unlocked = dash_unlocked
	cleared_enemies = (profile.get("cleared_enemies", []) as Array).duplicate()
	collected_pickups = (profile.get("collected_pickups", []) as Array).duplicate()
	discovered_rooms = (profile.get("discovered_rooms", []) as Array).duplicate()
	used_shortcuts = (profile.get("used_shortcuts", []) as Array).duplicate()
	var saved_position := profile.get("hero_position", [150.0, 320.0]) as Array
	if saved_position.size() >= 2:
		player.position = Vector2(float(saved_position[0]), float(saved_position[1]))

func _clear_room_entities() -> void:
	for node in enemies + pickups:
		if is_instance_valid(node):
			node.queue_free()
	enemies.clear()
	pickups.clear()
	if is_instance_valid(npc):
		npc.queue_free()
	if is_instance_valid(boss):
		boss.queue_free()

func _load_room(index: int) -> void:
	_clear_room_entities()
	room_index = clampi(index, 0, _last_room_index())
	var current_room_id := _room_id()
	if current_room_id != "" and current_room_id not in discovered_rooms:
		discovered_rooms.append(current_room_id)
	var palette := [Color("172a35"), Color("2b2436"), Color("20352f"), Color("272642"), Color("34301f"), Color("351f22")]
	RenderingServer.set_default_clear_color(palette[room_index % palette.size()])
	_build_room_decor()
	var rooms := _rooms()
	var room_data: Dictionary = rooms[room_index] if room_index < rooms.size() else {}
	_build_room_geometry(room_data)
	var enemy_positions := [Vector2(390, 190), Vector2(650, 390), Vector2(520, 420)]
	for enemy_index in range((room_data.get("enemies", []) as Array).size()):
		var enemy_data := (room_data.get("enemies", []) as Array)[enemy_index] as Dictionary
		_spawn_enemy(
			str(enemy_data.get("id", "enemy_%d" % enemy_index)),
			_vector_from(enemy_data.get("position", []), enemy_positions[enemy_index % enemy_positions.size()]),
			str(enemy_data.get("role", "stalker")),
			int(enemy_data.get("health", 3)),
			str(enemy_data.get("display_name", "Enemy"))
		)
	var pickup_positions := [Vector2(500, 330), Vector2(600, 180), Vector2(760, 430)]
	for pickup_index in range((room_data.get("pickups", []) as Array).size()):
		var pickup_data := (room_data.get("pickups", []) as Array)[pickup_index] as Dictionary
		_spawn_pickup(
			str(pickup_data.get("id", "pickup_%d" % pickup_index)),
			_vector_from(pickup_data.get("position", []), pickup_positions[pickup_index % pickup_positions.size()]),
			str(pickup_data.get("kind", "sparks")),
			int(pickup_data.get("amount", 1))
		)
	if room_data.get("npc") is Dictionary:
		_spawn_npc(
			_vector_from(room_data.get("npc_position", []), Vector2(760, 270)),
			room_data.get("npc") as Dictionary
		)
	if room_data.has("boss") and (forge_door_open or quest_stage in ["forge_open", "complete"]):
		var boss_data := room_data.get("boss", {}) as Dictionary
		_spawn_boss(_vector_from(boss_data.get("position", []), Vector2(760, 300)), boss_data)
	elif room_index == _last_room_index() and not forge_door_open:
		_spawn_npc(Vector2(820, 290), _quest_npc_data())
	_update_hud()

func _build_room_decor() -> void:
	for child in room_decor.get_children():
		child.queue_free()
	var colors := [Color("365469"), Color("5a4563"), Color("3e6657"), Color("4d4770"), Color("665c35"), Color("6b4037")]
	for index in range(5):
		var rune := Polygon2D.new()
		var x := 125.0 + float(index) * 185.0
		var y := 150.0 + float((index + room_index) % 3) * 130.0
		rune.polygon = PackedVector2Array([Vector2(-24, -4), Vector2(0, -18), Vector2(24, -4), Vector2(0, 18)])
		rune.position = Vector2(x, y)
		rune.color = Color(colors[room_index % colors.size()], 0.42)
		room_decor.add_child(rune)
	var rooms := ((_definition.get("room_plan", {}) as Dictionary).get("rooms", []) as Array)
	if room_index < rooms.size():
		var theme_id := str((rooms[room_index] as Dictionary).get("theme_id", "ember_ruins"))
		var theme_colors := {
			"ember_ruins": Color("d87a45"), "moon_archive": Color("82a7e8"),
			"verdant_foundry": Color("62bd8a"), "storm_crypt": Color("ac88df"),
			"sunken_sanctum": Color("52c5c7"), "glass_wilds": Color("c6d66a")
		}
		for index in range(4):
			var mote := Polygon2D.new()
			mote.polygon = PackedVector2Array([Vector2(0, -5), Vector2(4, 0), Vector2(0, 5), Vector2(-4, 0)])
			mote.position = Vector2(185 + index * 210, 116 + ((index + room_index) % 2) * 350)
			mote.color = Color(theme_colors.get(theme_id, Color("d87a45")), 0.82)
			room_decor.add_child(mote)

func _spawn_enemy(id: String, at: Vector2, role: String, health := 3, display_name := "Enemy") -> void:
	if id in cleared_enemies:
		return
	var enemy := SagaActionRpgEnemy.new()
	enemy.position = at
	enemy.configure({"id": id, "role": role, "health": health, "speed": 72.0, "name": display_name}, player)
	enemy.defeated.connect(_on_enemy_defeated)
	add_child(enemy)
	var role_asset := "enemy_" + role.to_lower().replace(" ", "_")
	if _asset(role_asset) == "":
		role_asset = "enemy"
	_attach_asset(enemy, role_asset, 48.0)
	enemies.append(enemy)

func _spawn_pickup(id: String, at: Vector2, kind: String, amount: int) -> void:
	if id in collected_pickups:
		return
	var pickup := SagaActionRpgPickup.new()
	pickup.position = at
	pickup.configure({"id": id, "kind": kind, "amount": amount})
	pickup.collected.connect(_on_pickup_collected)
	add_child(pickup)
	_attach_asset(pickup, "pickup", 34.0)
	pickups.append(pickup)

func _spawn_npc(at: Vector2, data: Dictionary) -> void:
	npc = SagaActionRpgNpc.new()
	npc.position = at
	npc.configure(data)
	add_child(npc)
	_attach_asset(npc, "npc", 54.0)

func _spawn_boss(at: Vector2, data := {}) -> void:
	if bool(ActionRpgProfile.snapshot().get("boss_defeated", false)):
		return
	boss = SagaActionRpgBoss.new()
	boss.position = at
	boss.configure(data, player)
	boss.defeated.connect(_on_boss_defeated)
	boss.phase_changed.connect(_on_boss_phase_changed)
	add_child(boss)
	_attach_asset(boss, "boss", 82.0)

func _on_player_swing(origin: Vector2, facing: Vector2) -> void:
	_slash_feedback(origin, facing)
	var connected := false
	for enemy in enemies:
		if not is_instance_valid(enemy) or enemy.health <= 0:
			continue
		var offset: Vector2 = enemy.global_position - origin
		if offset.length() <= 82.0 and offset.normalized().dot(facing) >= 0.25:
			if enemy.take_damage(1, facing * 110.0):
				connected = true
				_impact_feedback(enemy.global_position, Color("ffd08a"))
	if is_instance_valid(boss):
		var boss_offset := boss.global_position - origin
		if boss_offset.length() <= 92.0 and boss_offset.normalized().dot(facing) >= 0.15:
			if boss.take_damage(1):
				connected = true
				_impact_feedback(boss.global_position, Color("ff805c"))
	if connected:
		Sfx.play("hit")

func _slash_feedback(origin: Vector2, facing: Vector2) -> void:
	var slash := Line2D.new()
	slash.position = origin
	slash.z_index = 28
	slash.width = 7.0
	slash.default_color = Color(1.0, 0.87, 0.54, 0.9)
	var center_angle := facing.angle()
	for index in range(8):
		var angle := center_angle - 0.72 + 1.44 * float(index) / 7.0
		slash.add_point(Vector2(cos(angle), sin(angle)) * 67.0)
	add_child(slash)
	var tween := create_tween()
	tween.set_parallel(true)
	tween.tween_property(slash, "width", 1.0, 0.16)
	tween.tween_property(slash, "modulate:a", 0.0, 0.18)
	tween.chain().tween_callback(slash.queue_free)

func _impact_feedback(at: Vector2, color: Color) -> void:
	var burst := Polygon2D.new()
	burst.position = at
	burst.z_index = 30
	burst.polygon = PackedVector2Array([
		Vector2(0, -18), Vector2(6, -6), Vector2(20, 0), Vector2(6, 6),
		Vector2(0, 18), Vector2(-6, 6), Vector2(-20, 0), Vector2(-6, -6)
	])
	burst.color = color
	add_child(burst)
	var particles := CPUParticles2D.new()
	particles.position = at
	particles.z_index = 31
	particles.amount = 12
	particles.lifetime = 0.28
	particles.one_shot = true
	particles.explosiveness = 0.92
	particles.emission_shape = CPUParticles2D.EMISSION_SHAPE_SPHERE
	particles.emission_sphere_radius = 5.0
	particles.direction = Vector2.UP
	particles.spread = 180.0
	particles.initial_velocity_min = 55.0
	particles.initial_velocity_max = 125.0
	particles.gravity = Vector2(0, 110)
	particles.scale_amount_min = 1.5
	particles.scale_amount_max = 3.5
	particles.color = color
	add_child(particles)
	particles.finished.connect(particles.queue_free)
	var tween := create_tween()
	tween.set_parallel(true)
	tween.tween_property(burst, "scale", Vector2(1.8, 1.8), 0.16)
	tween.tween_property(burst, "modulate:a", 0.0, 0.18)
	tween.chain().tween_callback(burst.queue_free)

func _on_enemy_defeated(enemy_id: String) -> void:
	if enemy_id not in cleared_enemies:
		cleared_enemies.append(enemy_id)
		inventory.add_sparks(2)
		Sfx.play("pickup")

func _on_pickup_collected(pickup_id: String, kind: String, amount: int) -> void:
	Sfx.play("pickup")
	if pickup_id not in collected_pickups:
		collected_pickups.append(pickup_id)
	if kind == "sparks":
		inventory.add_sparks(amount)
	elif kind == "health":
		player.health = mini(player.max_health, player.health + amount)
	else:
		inventory.add_item(pickup_id, amount)
	_impact_feedback(player.global_position, Color("8ff5cf") if kind == "health" else Color("ffd56b"))
	if inventory.sparks >= _quest_cost() and quest_stage == "collect_sparks":
		quest_stage = "return_to_hermit"
	_update_hud()

func _on_player_defeated() -> void:
	state = "over"
	player.movement_locked = true
	Sfx.play("lose")
	_update_hud()

func _on_boss_phase_changed(_phase: int) -> void:
	Sfx.play("phase")
	_impact_feedback(boss.global_position, Color("ff4f72"))
	var pulse := ColorRect.new()
	pulse.position = Vector2.ZERO
	pulse.size = Vector2(1024, 576)
	pulse.color = Color(0.65, 0.05, 0.12, 0.24)
	var layer := CanvasLayer.new()
	layer.layer = 40
	layer.add_child(pulse)
	add_child(layer)
	var tween := create_tween()
	tween.tween_property(pulse, "modulate:a", 0.0, 0.42)
	tween.tween_callback(layer.queue_free)

func _on_boss_defeated() -> void:
	quest_stage = "complete"
	state = "won"
	var profile := _profile_snapshot()
	profile["boss_defeated"] = true
	ActionRpgProfile.checkpoint_memory(profile)
	Sfx.play("win")
	_update_hud()

func begin_dialogue() -> bool:
	if not is_instance_valid(npc) or dialogue_open:
		return false
	dialogue_open = true
	dialogue_index = 0
	player.movement_locked = true
	dialogue_panel.visible = true
	dialogue_label.text = "%s\n\n%s\n\n[X] continue" % [npc.speaker_name, npc.lines[0]]
	return true

func advance_dialogue() -> bool:
	if not dialogue_open:
		return false
	dialogue_index += 1
	if dialogue_index >= npc.lines.size():
		dialogue_open = false
		dialogue_panel.visible = false
		player.movement_locked = false
		if quest_stage == "return_to_hermit":
			turn_in_quest()
		return true
	dialogue_label.text = "%s\n\n%s\n\n[X] continue" % [npc.speaker_name, npc.lines[dialogue_index]]
	return true

func turn_in_quest() -> bool:
	if quest_stage != "return_to_hermit" or not inventory.spend_sparks(_quest_cost()):
		return false
	quest_stage = "forge_open"
	dash_unlocked = true
	forge_door_open = true
	player.dash_unlocked = true
	Sfx.play("phase")
	checkpoint_room()
	return true

func toggle_inventory() -> bool:
	inventory_open = not inventory_open
	inventory_panel.visible = inventory_open
	player.movement_locked = inventory_open or dialogue_open
	_update_inventory_panel()
	return inventory_open

func transition_room(direction: int) -> bool:
	# Compatibility surface for older probes and saves. Array order no longer
	# controls the world; positive and negative mean east and west exits.
	return transition_exit("east" if direction > 0 else "west")

func transition_exit(direction: String) -> bool:
	var exit := _exit_for(_room_id(), direction)
	if exit.is_empty():
		_clamp_to_playfield()
		return false
	var required_stage := str(exit.get("requires_quest_stage", ""))
	if required_stage != "" and quest_stage not in [required_stage, "complete"]:
		_clamp_to_playfield()
		return false
	if room_index == _last_room_index() and is_instance_valid(boss):
		_clamp_to_playfield()
		return false
	var target := _room_index_for_id(str(exit.get("target", "")))
	if target < 0:
		_clamp_to_playfield()
		return false
	if str(exit.get("kind", "")) == "shortcut":
		var edge_id := str(exit.get("edge_id", ""))
		if edge_id != "" and edge_id not in used_shortcuts:
			used_shortcuts.append(edge_id)
	room_index = target
	match direction:
		"east": player.position = Vector2(60, 320)
		"west": player.position = Vector2(964, 320)
		"north": player.position = Vector2(512, 510)
		"south": player.position = Vector2(512, 126)
	_load_room(room_index)
	_room_transition_feedback(direction)
	checkpoint_room()
	return true

func _clamp_to_playfield() -> void:
	player.position.x = clampf(player.position.x, 54.0, 970.0)
	player.position.y = clampf(player.position.y, 122.0, 514.0)

func _room_transition_feedback(direction: String) -> void:
	var layer := CanvasLayer.new()
	layer.layer = 35
	var curtain := ColorRect.new()
	curtain.position = Vector2.ZERO
	curtain.size = Vector2(1024, 576)
	curtain.color = Color(0.03, 0.055, 0.08, 0.72)
	layer.add_child(curtain)
	add_child(layer)
	var tween := create_tween()
	var offset: Vector2 = {
		"east": Vector2(96, 0), "west": Vector2(-96, 0),
		"north": Vector2(0, -72), "south": Vector2(0, 72)
	}.get(direction, Vector2.ZERO) as Vector2
	curtain.position = offset
	tween.set_parallel(true)
	tween.tween_property(curtain, "position", -offset, 0.28)
	tween.tween_property(curtain, "modulate:a", 0.0, 0.28)
	tween.chain().tween_callback(layer.queue_free)

func _profile_snapshot() -> Dictionary:
	return {
		"schema_version": 1,
		"room_index": room_index,
		"hero_position": [player.position.x, player.position.y],
		"hero_hp": player.health,
		"sparks": inventory.sparks,
		"items": inventory.items.duplicate(true),
		"quest_stage": quest_stage,
		"dash_unlocked": dash_unlocked,
		"boss_defeated": quest_stage == "complete",
		"collected_pickups": collected_pickups.duplicate(),
		"cleared_enemies": cleared_enemies.duplicate(),
		"discovered_rooms": discovered_rooms.duplicate(),
		"used_shortcuts": used_shortcuts.duplicate()
	}

func checkpoint_room() -> bool:
	checkpoint_data = _profile_snapshot()
	return ActionRpgProfile.checkpoint(checkpoint_data)

func restart_from_checkpoint() -> bool:
	if checkpoint_data.is_empty():
		checkpoint_data = ActionRpgProfile.snapshot()
	room_index = int(checkpoint_data.get("room_index", 0))
	inventory.restore({"sparks": checkpoint_data.get("sparks", 0), "items": checkpoint_data.get("items", {})})
	quest_stage = str(checkpoint_data.get("quest_stage", "collect_sparks"))
	dash_unlocked = bool(checkpoint_data.get("dash_unlocked", false))
	forge_door_open = quest_stage in ["forge_open", "complete"]
	player.restore(true)
	var saved_position := checkpoint_data.get("hero_position", [150.0, 320.0]) as Array
	player.position = Vector2(float(saved_position[0]), float(saved_position[1]))
	state = "playing"
	_load_room(room_index)
	return player.health == player.max_health and state == "playing"

func _quest_hint() -> String:
	match quest_stage:
		"collect_sparks": return _narrative_text("collect_objective", "Recover the quest relics")
		"return_to_hermit": return _narrative_text("return_objective", "Return to the quest giver")
		"forge_open": return _narrative_text("boss_objective", "Defeat the guardian")
		"complete": return _narrative_text("victory_text", "The journey is complete")
	return _narrative_text("quest_title", "Explore the world")

func _update_inventory_panel() -> void:
	if not is_instance_valid(inventory_label):
		return
	var item_lines: Array[String] = []
	for key in inventory.items:
		item_lines.append("%s x%d" % [_item_display_name(str(key)), int(inventory.items[key])])
	if item_lines.is_empty():
		item_lines.append("No gear collected")
	inventory_label.text = "INVENTORY\n\n%s  %d\n\n%s\n\n[C] close" % [_narrative_text("currency_name", "Quest Relics").to_upper(), inventory.sparks, "\n".join(item_lines)]

func _update_hud() -> void:
	if not is_instance_valid(hud_label):
		return
	hud_label.text = "HP %d/%d    %s %d    Z swing    X talk    C inventory" % [player.health, player.max_health, _narrative_text("currency_name", "RELICS").to_upper(), inventory.sparks]
	quest_label.text = "%s  %s" % [_narrative_text("quest_title", "QUEST").to_upper(), _quest_hint()]
	var rooms := ((_definition.get("room_plan", {}) as Dictionary).get("rooms", []) as Array)
	var room_name := "ROOM %d" % (room_index + 1)
	if room_index < rooms.size():
		room_name = str((rooms[room_index] as Dictionary).get("name", room_name))
	var exit_labels: Array[String] = []
	for direction in ["north", "south", "east", "west"]:
		var exit := _exit_for(_room_id(), direction)
		if not exit.is_empty():
			var marker: String = "?" if str(exit.get("kind", "")) == "optional_branch" else direction.left(1).to_upper()
			exit_labels.append(marker)
	var discovery := "%d/%d DISCOVERED" % [discovered_rooms.size(), _room_count()]
	room_label.text = "%s\n%s  %s" % [room_name.to_upper(), discovery, " ".join(exit_labels)]
	_update_inventory_panel()
	if state == "over":
		quest_label.text = "FALLEN — ENTER to restart at checkpoint"
	elif state == "won":
		quest_label.text = _narrative_text("victory_text", "QUEST COMPLETE").to_upper()

# Stable deterministic QA surface. These methods exercise the same state
# transitions used by input, collision, dialogue and combat code.
func qa_snapshot() -> Dictionary:
	return {
		"state": state, "room": room_index, "sparks": inventory.sparks,
		"quest": quest_stage, "dash": dash_unlocked, "inventory_open": inventory_open,
		"dialogue_open": dialogue_open, "hp": player.health,
		"boss_phase": boss.phase if is_instance_valid(boss) else 0
	}

func qa_reset_for_probe() -> bool:
	ActionRpgProfile.reset()
	state = "playing"
	room_index = 0
	quest_stage = "collect_sparks"
	dash_unlocked = false
	forge_door_open = false
	dialogue_open = false
	inventory_open = false
	inventory.restore({"sparks": 0, "items": {}})
	cleared_enemies.clear()
	collected_pickups.clear()
	discovered_rooms.clear()
	used_shortcuts.clear()
	checkpoint_data.clear()
	player.dash_unlocked = false
	player.restore(true)
	player.position = Vector2(150, 320)
	_load_room(0)
	return state == "playing" and room_index == 0 and inventory.sparks == 0

func qa_verify_narrative_identity() -> bool:
	var narrative := _narrative()
	var required := [
		"quest_title", "currency_name", "quest_giver_name", "boss_name", "enemy_name",
		"relic_name", "ability_name", "collect_objective", "return_objective",
		"boss_objective", "victory_text", "source_fingerprint"
	]
	for field in required:
		if str(narrative.get(field, "")).strip_edges() == "":
			return false
	var room_names := narrative.get("room_names", []) as Array
	if room_names.size() != _room_count():
		return false
	for index in range(_room_count()):
		if str((_rooms()[index] as Dictionary).get("name", "")) != str(room_names[index]):
			return false
	if not is_instance_valid(npc):
		_load_room(0)
	if not is_instance_valid(npc) or npc.speaker_name != str(narrative.get("quest_giver_name", "")):
		return false
	var expected_lines := narrative.get("dialogue_lines", []) as Array
	if npc.lines.size() != expected_lines.size():
		return false
	for index in range(expected_lines.size()):
		if npc.lines[index] != str(expected_lines[index]):
			return false
	_update_hud()
	return (
		str(narrative.get("currency_name", "")).to_upper() in hud_label.text
		and str(narrative.get("quest_title", "")).to_upper() in quest_label.text
		and str(narrative.get("collect_objective", "")) in quest_label.text
	)

func qa_verify_movement() -> bool:
	return player.qa_nudge(Vector2.RIGHT) > 10.0

func qa_verify_melee() -> Dictionary:
	var enemy := SagaActionRpgEnemy.new()
	enemy.position = player.position + Vector2(52, 0)
	enemy.configure({"id": "qa_enemy", "health": 2}, player)
	add_child(enemy)
	enemies.append(enemy)
	player.facing = Vector2.RIGHT
	var before := enemy.health
	player.attack_cooldown_left = 0.0
	var swung := player.attack()
	var result := {
		"melee": swung and enemy.health == before - 1,
		"enemy_state": enemy.state == "staggered" and enemy.stagger_left > 0.0
	}
	enemies.erase(enemy)
	enemy.queue_free()
	return result

func qa_verify_pickup_inventory() -> Dictionary:
	var before := inventory.sparks
	var charm_before := inventory.count("ember_charm")
	var qa_pickup := SagaActionRpgPickup.new()
	qa_pickup.configure({"id": "ember_charm", "kind": "item", "amount": 1})
	qa_pickup.collected.connect(_on_pickup_collected)
	add_child(qa_pickup)
	var collected := qa_pickup.collect_for(player)
	inventory.add_sparks(_quest_cost())
	quest_stage = "return_to_hermit"
	var opened := toggle_inventory()
	var listed := _item_display_name("ember_charm").to_lower() in inventory_label.text.to_lower() and str(inventory.sparks) in inventory_label.text
	toggle_inventory()
	qa_pickup.queue_free()
	return {
		"pickup": collected and qa_pickup.consumed and inventory.count("ember_charm") == charm_before + 1,
		"inventory": inventory.sparks == before + _quest_cost() and opened and listed and not inventory_open
	}

func qa_verify_dialogue_quest() -> Dictionary:
	if not is_instance_valid(npc):
		room_index = 0
		_load_room(0)
	var opened := begin_dialogue()
	var frozen := player.movement_locked
	var advanced := false
	while dialogue_open:
		advanced = advance_dialogue() or advanced
	if quest_stage == "return_to_hermit":
		turn_in_quest()
	return {
		"dialogue": opened and frozen and advanced and not player.movement_locked and not dialogue_open,
		"quest": quest_stage == "forge_open" and dash_unlocked and forge_door_open and inventory.sparks == 0
	}

func qa_verify_room_persistence() -> bool:
	if "foe_1_0" not in cleared_enemies:
		cleared_enemies.append("foe_1_0")
	if "vault_sparks" not in collected_pickups:
		collected_pickups.append("vault_sparks")
	room_index = 1
	_load_room(1)
	var enemy_stayed_cleared := not enemies.any(func(enemy): return enemy.enemy_id == "foe_1_0")
	var pickup_stayed_collected := not pickups.any(func(pickup): return pickup.pickup_id == "vault_sparks")
	var moved := transition_exit("east")
	return moved and _room_id() == "journey_3" and forge_door_open and enemy_stayed_cleared and pickup_stayed_collected

func qa_verify_world_graph() -> bool:
	# Prove the authored junction, optional branch and shortcut are runtime
	# travel—not metadata—and that discovery survives the route.
	room_index = 0
	_load_room(0)
	var start_id := _room_id()
	var entered_junction := transition_exit("east") and _room_id() == "rust_vault"
	var entered_branch := transition_exit("north") and _room_id() == "relic_branch"
	var took_shortcut := transition_exit("east") and _room_id() == "journey_3"
	var returned_to_junction := transition_exit("west") and _room_id() == "rust_vault"
	var returned_to_start := transition_exit("west") and _room_id() == start_id
	var optional_rooms := _world_graph().get("optional_rooms", []) as Array
	return (
		entered_junction and entered_branch and took_shortcut
		and returned_to_junction and returned_to_start
		and "relic_branch" in discovered_rooms
		and "relic_return_shortcut" in used_shortcuts
		and optional_rooms.has("relic_branch")
	)

func qa_verify_save_reload() -> bool:
	inventory.add_item("qa_relic", 1)
	var expected_count := inventory.count("qa_relic")
	var saved := checkpoint_room()
	var expected := ActionRpgProfile.snapshot()
	ActionRpgProfile.reset()
	var reloaded := ActionRpgProfile.load_profile()
	var loaded := ActionRpgProfile.snapshot()
	var loaded_position := loaded.get("hero_position", []) as Array
	var expected_position := expected.get("hero_position", []) as Array
	var position_matches := loaded_position.size() == 2 and expected_position.size() == 2
	if position_matches:
		position_matches = Vector2(float(loaded_position[0]), float(loaded_position[1])).is_equal_approx(
			Vector2(float(expected_position[0]), float(expected_position[1]))
		)
	var loaded_items := loaded.get("items", {}) as Dictionary
	var expected_items := expected.get("items", {}) as Dictionary
	var items_match := loaded_items.size() == expected_items.size()
	for key in expected_items:
		items_match = items_match and int(loaded_items.get(key, -1)) == int(expected_items[key])
	var checks := {
		"write": saved,
		"reload": reloaded,
		"position": position_matches,
		"room": int(loaded.get("room_index", -1)) == int(expected.get("room_index", -2)),
		"hp": int(loaded.get("hero_hp", -1)) == int(expected.get("hero_hp", -2)),
		"sparks": int(loaded.get("sparks", -1)) == int(expected.get("sparks", -2)),
		"quest": str(loaded.get("quest_stage", "")) == str(expected.get("quest_stage", "missing")),
		"dash": bool(loaded.get("dash_unlocked", false)) == bool(expected.get("dash_unlocked", true)),
		"items": items_match,
		"pickups": loaded.get("collected_pickups", []) == expected.get("collected_pickups", []),
		"enemies": loaded.get("cleared_enemies", []) == expected.get("cleared_enemies", []),
		"discovery": loaded.get("discovered_rooms", []) == expected.get("discovered_rooms", []),
		"shortcuts": loaded.get("used_shortcuts", []) == expected.get("used_shortcuts", []),
		"relic": int((loaded.get("items", {}) as Dictionary).get("qa_relic", 0)) == expected_count
	}
	print("[ACTION_RPG_SAVE] " + JSON.stringify(checks))
	return not checks.values().has(false)

func qa_verify_loss_restart() -> Dictionary:
	checkpoint_room()
	player.invulnerability_left = 0.0
	player.take_damage(player.max_health)
	var lost := state == "over" and player.health == 0
	var restarted := restart_from_checkpoint()
	return {
		"loss": lost,
		"restart": restarted and player.health == player.max_health and state == "playing"
	}

func qa_verify_boss_phases_and_win() -> Dictionary:
	quest_stage = "forge_open"
	forge_door_open = true
	var clean_profile := _profile_snapshot()
	clean_profile["boss_defeated"] = false
	ActionRpgProfile.checkpoint_memory(clean_profile)
	room_index = _last_room_index()
	_load_room(room_index)
	if not is_instance_valid(boss):
		return {"boss_phase": false, "win": false}
	boss.take_damage(ceili(float(boss.max_health) / 2.0))
	var phase_ok := boss.phase == 2
	boss.take_damage(boss.health)
	return {
		"boss_phase": phase_ok,
		"win": state == "won" and quest_stage == "complete"
	}
