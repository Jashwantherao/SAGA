class_name SagaRunAndGunPlayer
extends CharacterBody2D

signal health_changed(current: int, maximum: int)
signal died
signal fired(projectile: Node)

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
	health = max_health
	spawn_point = global_position
	health_changed.emit(health, max_health)

func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y += gravity * delta
	var axis := Input.get_axis("ui_left", "ui_right") if can_control else 0.0
	velocity.x = move_toward(velocity.x, axis * move_speed, move_speed * 8.0 * delta)
	if axis != 0.0:
		facing = sign(axis)
	if can_control and Input.is_action_just_pressed("ui_up") and is_on_floor():
		velocity.y = jump_velocity
	# Autoplay's first ui_accept dismisses title screens in classic templates.
	# This pack starts in gameplay, so treating that harness pulse as a shot
	# would inflate idle motion and hide the player's real input response.
	if can_control and Input.is_action_just_pressed("ui_accept") and not "--autoplay" in OS.get_cmdline_user_args():
		fire()
	move_and_slide()
	global_position.x = clampf(global_position.x, 24.0, 4900.0)
	if is_instance_valid(player_sprite):
		Anim.walk(player_sprite, abs(velocity.x) > 5.0, velocity.x)

func fire() -> Node:
	if not can_control:
		return null
	var projectile := SagaRunAndGunProjectile.new()
	get_parent().add_child(projectile)
	projectile.global_position = global_position + Vector2(facing * 34.0, -5.0)
	projectile.configure({
		"direction": Vector2(facing, 0),
		"speed": projectile_speed,
		"damage": 1,
		"faction": faction,
	})
	fired.emit(projectile)
	Sfx.play("pickup")
	return projectile

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
	health_changed.emit(health, max_health)
