class_name SagaRunAndGunEnemy
extends CharacterBody2D

signal died(enemy: Node)

var faction := "enemy"
var target: Node2D
var move_speed := 90.0
var gravity := 1500.0
var max_health := 2
var health := 2
var patrol_origin := Vector2.ZERO
var patrol_distance := 120.0
var chase_range := 310.0
var direction := -1.0
var contact_damage := 1
var contact_cooldown := 0.0
var actor_sprite: Sprite2D
var role := "scout"
var projectile_speed := 430.0
var shot_cooldown := 0.0
var flight_time := 0.0
var flight_origin_y := 0.0

func _ready() -> void:
	add_to_group("run_and_gun_enemies")
	collision_layer = 2
	collision_mask = 1 | 2
	var shape := CollisionShape2D.new()
	var capsule := CapsuleShape2D.new()
	capsule.radius = 15.0
	capsule.height = 46.0
	shape.shape = capsule
	add_child(shape)
	patrol_origin = global_position
	flight_origin_y = global_position.y

func configure(options: Dictionary) -> void:
	target = options.get("target")
	role = str(options.get("role", role))
	move_speed = float(options.get("move_speed", move_speed))
	max_health = int(options.get("health", max_health))
	projectile_speed = float(options.get("projectile_speed", projectile_speed))
	if role == "scout":
		move_speed *= 1.35
	elif role == "bruiser":
		move_speed *= 0.72
		max_health += 2
	elif role == "hunter":
		max_health += 1
	elif role == "turret":
		move_speed = 0.0
		max_health += 1
	elif role == "flyer":
		gravity = 0.0
		move_speed *= 1.05
	health = max_health
	patrol_distance = float(options.get("patrol_distance", patrol_distance))
	patrol_origin = global_position

func _physics_process(delta: float) -> void:
	if role != "flyer" and not is_on_floor():
		velocity.y += gravity * delta
	if "--autoplay" in OS.get_cmdline_user_args():
		velocity.x = 0.0
		move_and_slide()
		return
	contact_cooldown = maxf(0.0, contact_cooldown - delta)
	shot_cooldown = maxf(0.0, shot_cooldown - delta)
	if role == "turret":
		velocity = Vector2.ZERO
		_try_fire(1.05)
		return
	if role == "flyer":
		flight_time += delta
		if is_instance_valid(target):
			direction = sign(target.global_position.x - global_position.x)
		velocity.x = direction * move_speed
		velocity.y = sin(flight_time * 2.4) * 72.0
		move_and_slide()
		_try_fire(1.55)
		_apply_contact_damage()
		if is_instance_valid(actor_sprite):
			Anim.walk(actor_sprite, true, velocity.x)
		return
	if is_instance_valid(target) and global_position.distance_to(target.global_position) < chase_range:
		direction = sign(target.global_position.x - global_position.x)
	elif abs(global_position.x - patrol_origin.x) > patrol_distance:
		direction = -sign(global_position.x - patrol_origin.x)
	if role == "hunter" and is_instance_valid(target) and global_position.distance_to(target.global_position) < 260.0:
		velocity.x = 0.0
		_try_fire(1.35)
	else:
		velocity.x = direction * move_speed
	move_and_slide()
	_apply_contact_damage()
	if is_instance_valid(actor_sprite):
		Anim.walk(actor_sprite, true, velocity.x)

func _apply_contact_damage() -> void:
	if is_instance_valid(target) and global_position.distance_to(target.global_position) < 42.0 and contact_cooldown <= 0.0:
		target.take_damage(contact_damage)
		contact_cooldown = 0.8

func _try_fire(interval: float) -> void:
	if shot_cooldown > 0.0 or not is_instance_valid(target):
		return
	if global_position.distance_to(target.global_position) > 520.0:
		return
	var projectile := SagaRunAndGunProjectile.new()
	get_parent().add_child(projectile)
	projectile.global_position = global_position + Vector2(0, -6)
	projectile.configure({
		"direction": global_position.direction_to(target.global_position),
		"speed": projectile_speed,
		"damage": 1,
		"faction": faction,
		"weapon_id": "enemy_%s" % role,
	})
	shot_cooldown = interval

func role_profile() -> Dictionary:
	return {
		"role": role,
		"mobile": role != "turret",
		"ranged": role in ["hunter", "turret", "flyer"],
		"flying": role == "flyer",
		"armored": role == "bruiser",
	}

func take_damage(amount: int) -> void:
	if amount <= 0 or health <= 0:
		return
	health = maxi(0, health - amount)
	if is_instance_valid(actor_sprite):
		Anim.flash(actor_sprite, Color("fff17a"))
	if health == 0:
		died.emit(self)
		queue_free()
