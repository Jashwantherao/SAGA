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

func configure(options: Dictionary) -> void:
	target = options.get("target")
	move_speed = float(options.get("move_speed", move_speed))
	max_health = int(options.get("health", max_health))
	health = max_health
	patrol_distance = float(options.get("patrol_distance", patrol_distance))
	patrol_origin = global_position

func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y += gravity * delta
	if "--autoplay" in OS.get_cmdline_user_args():
		velocity.x = 0.0
		move_and_slide()
		return
	contact_cooldown = maxf(0.0, contact_cooldown - delta)
	if is_instance_valid(target) and global_position.distance_to(target.global_position) < chase_range:
		direction = sign(target.global_position.x - global_position.x)
	elif abs(global_position.x - patrol_origin.x) > patrol_distance:
		direction = -sign(global_position.x - patrol_origin.x)
	velocity.x = direction * move_speed
	move_and_slide()
	if is_instance_valid(target) and global_position.distance_to(target.global_position) < 42.0 and contact_cooldown <= 0.0:
		target.take_damage(contact_damage)
		contact_cooldown = 0.8
	if is_instance_valid(actor_sprite):
		Anim.walk(actor_sprite, true, velocity.x)

func take_damage(amount: int) -> void:
	if amount <= 0 or health <= 0:
		return
	health = maxi(0, health - amount)
	if is_instance_valid(actor_sprite):
		Anim.flash(actor_sprite, Color("fff17a"))
	if health == 0:
		died.emit(self)
		queue_free()
