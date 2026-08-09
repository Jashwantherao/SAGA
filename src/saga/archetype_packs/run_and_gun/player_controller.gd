class_name SagaRunAndGunPlayer
extends CharacterBody2D

signal health_changed(current: int, maximum: int)
signal died
signal fired(projectile: Node)
signal weapon_changed(weapon_id: String, ammo: int)

const WEAPONS = {
	"pulse": {"projectiles": 1, "spread": 0.0, "damage": 1, "speed_scale": 1.0, "cooldown": 0.18, "blast_radius": 0.0},
	"spread": {"projectiles": 3, "spread": 14.0, "damage": 1, "speed_scale": 0.86, "cooldown": 0.42, "blast_radius": 0.0},
	"launcher": {"projectiles": 1, "spread": 0.0, "damage": 3, "speed_scale": 0.62, "cooldown": 0.68, "blast_radius": 92.0},
}

var faction := "player"
var move_speed := 250.0
var jump_velocity := -520.0
var gravity := 1500.0
var projectile_speed := 700.0
var max_health := 5
var health := 5
var can_control := true
var facing := 1.0
var spawn_point := Vector2.ZERO
var player_sprite: Sprite2D
var weapon_id := "pulse"
var weapon_ammo := -1
var fire_cooldown := 0.0
var world_limit := 4900.0
var arena_min_x := 24.0
var arena_max_x := 4900.0
var weapon_inventory: Dictionary = {"pulse": -1}
var base_move_speed := 250.0
var base_max_health := 5
var progression_damage_bonus := 0

func _ready() -> void:
	add_to_group("run_and_gun_player")
	collision_layer = 1
	collision_mask = 1 | 2
	var shape := CollisionShape2D.new()
	var capsule := CapsuleShape2D.new()
	capsule.radius = 15.0
	capsule.height = 48.0
	shape.shape = capsule
	add_child(shape)

func configure(options: Dictionary) -> void:
	move_speed = float(options.get("move_speed", move_speed))
	projectile_speed = float(options.get("projectile_speed", projectile_speed))
	max_health = int(options.get("health", max_health))
	base_move_speed = move_speed
	base_max_health = max_health
	world_limit = float(options.get("world_limit", world_limit))
	arena_max_x = world_limit
	health = max_health
	reset_loadout()
	spawn_point = global_position
	health_changed.emit(health, max_health)

func _physics_process(delta: float) -> void:
	fire_cooldown = maxf(0.0, fire_cooldown - delta)
	if not is_on_floor():
		velocity.y += gravity * delta
	var axis := Input.get_axis("ui_left", "ui_right") if can_control else 0.0
	velocity.x = move_toward(velocity.x, axis * move_speed, move_speed * 8.0 * delta)
	if axis != 0.0:
		facing = sign(axis)
	if can_control and Input.is_action_just_pressed("ui_up") and is_on_floor():
		velocity.y = jump_velocity
	if can_control and Input.is_action_just_pressed("ui_focus_next"):
		cycle_weapon()
	# Autoplay's first ui_accept dismisses title screens in classic templates.
	# This pack starts in gameplay, so treating that harness pulse as a shot
	# would inflate idle motion and hide the player's real input response.
	if can_control and Input.is_action_just_pressed("ui_accept") and not "--autoplay" in OS.get_cmdline_user_args():
		fire()
	move_and_slide()
	global_position.x = clampf(global_position.x, arena_min_x, arena_max_x)
	if is_instance_valid(player_sprite):
		Anim.walk(player_sprite, abs(velocity.x) > 5.0, velocity.x)

func fire() -> Node:
	if not can_control or fire_cooldown > 0.0:
		return null
	if weapon_ammo == 0:
		equip_weapon("pulse", -1)
	var definition := WEAPONS.get(weapon_id, WEAPONS["pulse"]) as Dictionary
	var projectile_count := int(definition.get("projectiles", 1))
	var spread := float(definition.get("spread", 0.0))
	var first_projectile: Node = null
	for index in projectile_count:
		var projectile := SagaRunAndGunProjectile.new()
		get_parent().add_child(projectile)
		projectile.global_position = global_position + Vector2(facing * 34.0, -5.0)
		var offset := float(index) - float(projectile_count - 1) / 2.0
		projectile.configure({
			"direction": Vector2(facing, 0).rotated(deg_to_rad(offset * spread)),
			"speed": projectile_speed * float(definition.get("speed_scale", 1.0)),
			"damage": int(definition.get("damage", 1)) + progression_damage_bonus,
			"blast_radius": float(definition.get("blast_radius", 0.0)),
			"weapon_id": weapon_id,
			"faction": faction,
		})
		if first_projectile == null:
			first_projectile = projectile
		fired.emit(projectile)
	fire_cooldown = float(definition.get("cooldown", 0.2))
	if weapon_ammo > 0:
		weapon_ammo -= 1
		weapon_inventory[weapon_id] = weapon_ammo
		weapon_changed.emit(weapon_id, weapon_ammo)
	Sfx.play("pickup")
	return first_projectile

func equip_weapon(next_weapon: String, ammo: int) -> bool:
	if not WEAPONS.has(next_weapon):
		return false
	weapon_id = next_weapon
	weapon_ammo = -1 if next_weapon == "pulse" else maxi(1, ammo)
	weapon_inventory[weapon_id] = weapon_ammo
	fire_cooldown = 0.0
	weapon_changed.emit(weapon_id, weapon_ammo)
	return true

func reset_loadout() -> void:
	weapon_inventory = {"pulse": -1}
	equip_weapon("pulse", -1)

func cycle_weapon() -> void:
	var order := ["pulse", "spread", "launcher"]
	var current := order.find(weapon_id)
	for offset in range(1, order.size() + 1):
		var candidate: String = order[(current + offset) % order.size()]
		if weapon_inventory.has(candidate) and int(weapon_inventory[candidate]) != 0:
			weapon_id = candidate
			weapon_ammo = int(weapon_inventory[candidate])
			fire_cooldown = 0.0
			weapon_changed.emit(weapon_id, weapon_ammo)
			return

func weapon_snapshot() -> Dictionary:
	var definition := WEAPONS.get(weapon_id, WEAPONS["pulse"]) as Dictionary
	return {
		"id": weapon_id,
		"ammo": weapon_ammo,
		"projectiles": int(definition.get("projectiles", 1)),
		"damage": int(definition.get("damage", 1)) + progression_damage_bonus,
		"blast_radius": float(definition.get("blast_radius", 0.0)),
		"inventory_size": weapon_inventory.size(),
		"progression_damage_bonus": progression_damage_bonus,
	}

func apply_progression(upgrades: Dictionary, unlocked_weapons: Array) -> void:
	var firepower := clampi(int(upgrades.get("firepower", 0)), 0, 3)
	var mobility := clampi(int(upgrades.get("mobility", 0)), 0, 3)
	var vitality := clampi(int(upgrades.get("vitality", 0)), 0, 3)
	progression_damage_bonus = firepower
	move_speed = base_move_speed * (1.0 + float(mobility) * 0.08)
	max_health = base_max_health + vitality * 2
	health = mini(max_health, maxi(1, health))
	for unlocked in unlocked_weapons:
		var weapon := str(unlocked)
		if weapon == "spread" and not weapon_inventory.has(weapon):
			weapon_inventory[weapon] = 18
		elif weapon == "launcher" and not weapon_inventory.has(weapon):
			weapon_inventory[weapon] = 6
	health_changed.emit(health, max_health)

func set_arena_lock(minimum_x: float, maximum_x: float) -> void:
	arena_min_x = maxf(24.0, minimum_x)
	arena_max_x = minf(world_limit, maximum_x)

func clear_arena_lock() -> void:
	arena_min_x = 24.0
	arena_max_x = world_limit

func take_damage(amount: int) -> void:
	if not can_control or amount <= 0:
		return
	health = maxi(0, health - amount)
	health_changed.emit(health, max_health)
	if is_instance_valid(player_sprite):
		Anim.flash(player_sprite)
	Sfx.play("hit")
	if health == 0:
		can_control = false
		velocity = Vector2.ZERO
		died.emit()

func heal(amount: int) -> void:
	if amount <= 0 or health <= 0:
		return
	health = mini(max_health, health + amount)
	health_changed.emit(health, max_health)

func set_checkpoint(position: Vector2) -> void:
	spawn_point = position

func reset_at_checkpoint() -> void:
	global_position = spawn_point
	health = max_health
	velocity = Vector2.ZERO
	can_control = true
	reset_loadout()
	health_changed.emit(health, max_health)
