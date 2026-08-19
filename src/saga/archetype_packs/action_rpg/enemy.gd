class_name SagaActionRpgEnemy
extends CharacterBody2D

signal defeated(enemy_id: String)

var enemy_id := "enemy"
var role := "stalker"
var max_health := 3
var health := 3
var move_speed := 72.0
var detection_radius := 230.0
var attack_radius := 34.0
var state := "patrol"
var target: SagaActionRpgPlayer
var home := Vector2.ZERO
var patrol_offset := 0.0
var stagger_left := 0.0
var attack_cooldown := 0.0

func _ready() -> void:
	add_to_group("action_rpg_enemies")
	collision_layer = 4
	collision_mask = 1 | 2
	home = position
	var collision := CollisionShape2D.new()
	var shape := CircleShape2D.new()
	shape.radius = 13.0
	collision.shape = shape
	add_child(collision)
	var visual := Polygon2D.new()
	visual.polygon = PackedVector2Array([Vector2(-14, -10), Vector2(10, -14), Vector2(16, 4), Vector2(5, 14), Vector2(-15, 10)])
	visual.color = Color("a84b3f") if role == "stalker" else Color("8f6249")
	add_child(visual)

func configure(data: Dictionary, player_target: SagaActionRpgPlayer) -> void:
	enemy_id = str(data.get("id", enemy_id))
	role = str(data.get("role", role))
	max_health = int(data.get("health", max_health))
	health = max_health
	move_speed = float(data.get("speed", move_speed))
	target = player_target

func _physics_process(delta: float) -> void:
	if health <= 0 or not is_instance_valid(target):
		velocity = Vector2.ZERO
		return
	stagger_left = maxf(0.0, stagger_left - delta)
	attack_cooldown = maxf(0.0, attack_cooldown - delta)
	if stagger_left > 0.0:
		state = "staggered"
		velocity = Vector2.ZERO
		move_and_slide()
		return
	var distance := global_position.distance_to(target.global_position)
	if distance <= attack_radius:
		state = "attack"
		velocity = Vector2.ZERO
		if attack_cooldown <= 0.0:
			target.take_damage(1)
			attack_cooldown = 1.2
	elif distance <= detection_radius:
		state = "chase"
		velocity = global_position.direction_to(target.global_position) * move_speed
	else:
		state = "patrol"
		patrol_offset += delta * 1.3
		var patrol_target := home + Vector2(sin(patrol_offset) * 55.0, 0.0)
		velocity = global_position.direction_to(patrol_target) * move_speed * 0.45
	move_and_slide()

func take_damage(amount: int, knockback := Vector2.ZERO) -> bool:
	if health <= 0 or amount <= 0:
		return false
	health = maxi(0, health - amount)
	stagger_left = 0.5
	state = "staggered"
	velocity = knockback
	if health == 0:
		state = "defeated"
		collision_layer = 0
		collision_mask = 0
		defeated.emit(enemy_id)
		visible = false
	return true
