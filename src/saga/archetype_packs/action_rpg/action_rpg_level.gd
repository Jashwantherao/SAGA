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

func level_definition() -> Dictionary:
	return {}

func _ready() -> void:
	add_to_group("saga_action_rpg_level")
	_definition = level_definition()
	RenderingServer.set_default_clear_color(Color("10151d"))
	_build_background()
	_build_room_shell()
	room_decor = Node2D.new()
	room_decor.z_index = -20
	add_child(room_decor)
	_build_player()
	_build_hud()
	_restore_or_begin()
	_load_room(room_index)
	checkpoint_room()

func _process(_delta: float) -> void:
	if not is_instance_valid(player):
		return
	var x_pressed := Input.is_key_pressed(KEY_X)
	if x_pressed and not _x_latched:
		if dialogue_open:
			advance_dialogue()
		elif room_index == 0 and player.position.distance_to(npc.position) < 95.0:
			begin_dialogue()
	_x_latched = x_pressed
	var c_pressed := Input.is_key_pressed(KEY_C)
	if c_pressed and not _c_latched:
		toggle_inventory()
	_c_latched = c_pressed
	if state == "over" and Input.is_action_just_pressed("ui_accept"):
		restart_from_checkpoint()
	if state == "playing" and not dialogue_open and not inventory_open:
		if player.position.x >= 985.0:
			transition_room(1)
		elif player.position.x <= 39.0:
			transition_room(-1)
	_update_hud()

func _asset(name: String) -> String:
	return str((_definition.get("assets", {}) as Dictionary).get(name, ""))

func _attach_asset(node: Node2D, asset_name: String, max_size: float) -> bool:
	var path := _asset(asset_name)
	if path == "":
		return false
	var texture := load(path) as Texture2D
	if texture == null:
		return false
	var sprite := Sprite2D.new()
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

func _wall(position: Vector2, size: Vector2) -> void:
	var wall := StaticBody2D.new()
	wall.position = position
	wall.collision_layer = 1
	wall.collision_mask = 2 | 4
	var collision := CollisionShape2D.new()
	var shape := RectangleShape2D.new()
	shape.size = size
	collision.shape = shape
	wall.add_child(collision)
	var visual := Polygon2D.new()
	visual.polygon = PackedVector2Array([Vector2(-size.x / 2, -size.y / 2), Vector2(size.x / 2, -size.y / 2), Vector2(size.x / 2, size.y / 2), Vector2(-size.x / 2, size.y / 2)])
	visual.color = Color("273846")
	wall.add_child(visual)
	add_child(wall)

func _build_room_shell() -> void:
	_wall(Vector2(512, 76), Vector2(1024, 28))
	_wall(Vector2(512, 562), Vector2(1024, 28))
	_wall(Vector2(12, 288), Vector2(24, 576))
	_wall(Vector2(1012, 288), Vector2(24, 576))
	for position in [Vector2(340, 220), Vector2(680, 390)]:
		_wall(position, Vector2(88, 38))

func _build_player() -> void:
	player = SagaActionRpgPlayer.new()
	player.move_speed = float(_definition.get("move_speed", 180.0))
	player.max_health = int(_definition.get("player_health", 5))
	player.health = player.max_health
	player.position = Vector2(150, 320)
	player.swing_requested.connect(_on_player_swing)
	player.defeated.connect(_on_player_defeated)
	add_child(player)
	var path := _asset("hero")
	if path != "":
		var texture := load(path) as Texture2D
		if texture != null:
			var sprite := Sprite2D.new()
			sprite.texture = texture
			sprite.scale = Vector2.ONE * minf(54.0 / maxf(texture.get_width(), 1), 54.0 / maxf(texture.get_height(), 1))
			sprite.position.y = -8
			player.add_child(sprite)

func _build_hud() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var backing := ColorRect.new()
	backing.position = Vector2(12, 10)
	backing.size = Vector2(1000, 62)
	backing.color = Color(0.025, 0.045, 0.065, 0.92)
	layer.add_child(backing)
	hud_label = Label.new()
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
	room_index = clampi(int(profile.get("room_index", 0)), 0, 2)
	player.health = clampi(int(profile.get("hero_hp", player.max_health)), 1, player.max_health)
	inventory.restore({"sparks": profile.get("sparks", 0), "items": profile.get("items", {})})
	quest_stage = str(profile.get("quest_stage", "collect_sparks"))
	dash_unlocked = bool(profile.get("dash_unlocked", false))
	forge_door_open = quest_stage in ["forge_open", "complete"]
	player.dash_unlocked = dash_unlocked
	cleared_enemies = (profile.get("cleared_enemies", []) as Array).duplicate()
	collected_pickups = (profile.get("collected_pickups", []) as Array).duplicate()
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
	room_index = clampi(index, 0, 2)
	var palette := [Color("172a35"), Color("2b2436"), Color("351f22")]
	RenderingServer.set_default_clear_color(palette[room_index])
	_build_room_decor()
	var rooms := ((_definition.get("room_plan", {}) as Dictionary).get("rooms", []) as Array)
	var room_data: Dictionary = rooms[room_index] if room_index < rooms.size() else {}
	var enemy_positions := [Vector2(390, 190), Vector2(650, 390), Vector2(520, 420)]
	for enemy_index in range((room_data.get("enemies", []) as Array).size()):
		var enemy_data := (room_data.get("enemies", []) as Array)[enemy_index] as Dictionary
		_spawn_enemy(
			str(enemy_data.get("id", "enemy_%d" % enemy_index)),
			enemy_positions[enemy_index % enemy_positions.size()],
			str(enemy_data.get("role", "stalker")),
			int(enemy_data.get("health", 3))
		)
	var pickup_positions := [Vector2(500, 330), Vector2(600, 180), Vector2(760, 430)]
	for pickup_index in range((room_data.get("pickups", []) as Array).size()):
		var pickup_data := (room_data.get("pickups", []) as Array)[pickup_index] as Dictionary
		_spawn_pickup(
			str(pickup_data.get("id", "pickup_%d" % pickup_index)),
			pickup_positions[pickup_index % pickup_positions.size()],
			str(pickup_data.get("kind", "sparks")),
			int(pickup_data.get("amount", 1))
		)
	if str(room_data.get("npc", "")) != "":
		_spawn_npc(Vector2(760, 270))
	if room_data.has("boss") and (forge_door_open or quest_stage in ["forge_open", "complete"]):
		_spawn_boss(Vector2(760, 300), room_data.get("boss", {}) as Dictionary)
	elif room_index == 2 and not forge_door_open:
		_spawn_npc(Vector2(820, 290))
	_update_hud()

func _build_room_decor() -> void:
	for child in room_decor.get_children():
		child.queue_free()
	var colors := [Color("365469"), Color("5a4563"), Color("6b4037")]
	for index in range(5):
		var rune := Polygon2D.new()
		var x := 125.0 + float(index) * 185.0
		var y := 150.0 + float((index + room_index) % 3) * 130.0
		rune.polygon = PackedVector2Array([Vector2(-24, -4), Vector2(0, -18), Vector2(24, -4), Vector2(0, 18)])
		rune.position = Vector2(x, y)
		rune.color = Color(colors[room_index], 0.42)
		room_decor.add_child(rune)

func _spawn_enemy(id: String, at: Vector2, role: String, health := 3) -> void:
	if id in cleared_enemies:
		return
	var enemy := SagaActionRpgEnemy.new()
	enemy.position = at
	enemy.configure({"id": id, "role": role, "health": health, "speed": 72.0}, player)
	enemy.defeated.connect(_on_enemy_defeated)
	add_child(enemy)
	_attach_asset(enemy, "enemy", 48.0)
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

func _spawn_npc(at: Vector2) -> void:
	npc = SagaActionRpgNpc.new()
	npc.position = at
	add_child(npc)
	_attach_asset(npc, "npc", 54.0)

func _spawn_boss(at: Vector2, data := {}) -> void:
	if bool(ActionRpgProfile.snapshot().get("boss_defeated", false)):
		return
	boss = SagaActionRpgBoss.new()
	boss.position = at
	boss.configure(data, player)
	boss.defeated.connect(_on_boss_defeated)
	add_child(boss)
	_attach_asset(boss, "boss", 82.0)

func _on_player_swing(origin: Vector2, facing: Vector2) -> void:
	for enemy in enemies:
		if not is_instance_valid(enemy) or enemy.health <= 0:
			continue
		var offset: Vector2 = enemy.global_position - origin
		if offset.length() <= 82.0 and offset.normalized().dot(facing) >= 0.25:
			enemy.take_damage(1, facing * 110.0)
	if is_instance_valid(boss):
		var boss_offset := boss.global_position - origin
		if boss_offset.length() <= 92.0 and boss_offset.normalized().dot(facing) >= 0.15:
			boss.take_damage(1)

func _on_enemy_defeated(enemy_id: String) -> void:
	if enemy_id not in cleared_enemies:
		cleared_enemies.append(enemy_id)
		inventory.add_sparks(2)

func _on_pickup_collected(pickup_id: String, kind: String, amount: int) -> void:
	if pickup_id not in collected_pickups:
		collected_pickups.append(pickup_id)
	if kind == "sparks":
		inventory.add_sparks(amount)
	else:
		inventory.add_item(pickup_id, amount)
	if inventory.sparks >= 10 and quest_stage == "collect_sparks":
		quest_stage = "return_to_hermit"
	_update_hud()

func _on_player_defeated() -> void:
	state = "over"
	player.movement_locked = true
	_update_hud()

func _on_boss_defeated() -> void:
	quest_stage = "complete"
	state = "won"
	var profile := _profile_snapshot()
	profile["boss_defeated"] = true
	ActionRpgProfile.checkpoint_memory(profile)
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
	if quest_stage != "return_to_hermit" or not inventory.spend_sparks(10):
		return false
	quest_stage = "forge_open"
	dash_unlocked = true
	forge_door_open = true
	player.dash_unlocked = true
	checkpoint_room()
	return true

func toggle_inventory() -> bool:
	inventory_open = not inventory_open
	inventory_panel.visible = inventory_open
	player.movement_locked = inventory_open or dialogue_open
	_update_inventory_panel()
	return inventory_open

func transition_room(direction: int) -> bool:
	var target := room_index + direction
	if target < 0 or target > 2:
		player.position.x = clampf(player.position.x, 40.0, 984.0)
		return false
	if target == 2 and quest_stage not in ["forge_open", "complete"]:
		player.position.x = 960.0
		return false
	room_index = target
	player.position = Vector2(60 if direction > 0 else 964, 320)
	_load_room(room_index)
	checkpoint_room()
	return true

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
		"cleared_enemies": cleared_enemies.duplicate()
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
		"collect_sparks": return "Gather 10 sparks for the Ember Hermit"
		"return_to_hermit": return "Return to the Ember Hermit"
		"forge_open": return "Enter the forge and defeat its warden"
		"complete": return "The heart-forge burns again"
	return "Explore the keep"

func _update_inventory_panel() -> void:
	if not is_instance_valid(inventory_label):
		return
	var item_lines: Array[String] = []
	for key in inventory.items:
		item_lines.append("%s x%d" % [str(key).replace("_", " ").capitalize(), int(inventory.items[key])])
	if item_lines.is_empty():
		item_lines.append("No gear collected")
	inventory_label.text = "INVENTORY\n\nSPARKS  %d\n\n%s\n\n[C] close" % [inventory.sparks, "\n".join(item_lines)]

func _update_hud() -> void:
	if not is_instance_valid(hud_label):
		return
	hud_label.text = "HP %d/%d    SPARKS %d    Z swing    X talk    C inventory" % [player.health, player.max_health, inventory.sparks]
	quest_label.text = "QUEST  " + _quest_hint()
	room_label.text = "ROOM %d/3\n%s" % [room_index + 1, "SHIFT DASH" if dash_unlocked else ""]
	_update_inventory_panel()
	if state == "over":
		quest_label.text = "FALLEN — ENTER to restart at checkpoint"
	elif state == "won":
		quest_label.text = "FORGE RELIT — QUEST COMPLETE"

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
	checkpoint_data.clear()
	player.dash_unlocked = false
	player.restore(true)
	player.position = Vector2(150, 320)
	_load_room(0)
	return state == "playing" and room_index == 0 and inventory.sparks == 0

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
	inventory.add_sparks(10)
	quest_stage = "return_to_hermit"
	var opened := toggle_inventory()
	var listed := "ember charm" in inventory_label.text.to_lower() and str(inventory.sparks) in inventory_label.text
	toggle_inventory()
	qa_pickup.queue_free()
	return {
		"pickup": collected and qa_pickup.consumed and inventory.count("ember_charm") == charm_before + 1,
		"inventory": inventory.sparks == before + 10 and opened and listed and not inventory_open
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
	if "stalker_vault_a" not in cleared_enemies:
		cleared_enemies.append("stalker_vault_a")
	if "vault_sparks" not in collected_pickups:
		collected_pickups.append("vault_sparks")
	room_index = 1
	_load_room(1)
	var enemy_stayed_cleared := not enemies.any(func(enemy): return enemy.enemy_id == "stalker_vault_a")
	var pickup_stayed_collected := not pickups.any(func(pickup): return pickup.pickup_id == "vault_sparks")
	var moved := transition_room(1)
	return moved and room_index == 2 and forge_door_open and enemy_stayed_cleared and pickup_stayed_collected

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
	room_index = 2
	_load_room(2)
	if not is_instance_valid(boss):
		return {"boss_phase": false, "win": false}
	boss.take_damage(ceili(float(boss.max_health) / 2.0))
	var phase_ok := boss.phase == 2
	boss.take_damage(boss.health)
	return {
		"boss_phase": phase_ok,
		"win": state == "won" and quest_stage == "complete"
	}
