class_name SagaActionRpgBoss
extends CharacterBody2D

signal phase_changed(phase: int)
signal defeated

var max_health := 12
var health := 12
var phase := 1
var state := "idle"
var target: SagaActionRpgPlayer
var telegraph_left := 0.0
var attack_cooldown := 1.5

func configure(data: Dictionary, player_target: SagaActionRpgPlayer) -> void:
	max_health = maxi(2, int(data.get("health", max_health)))
	health = max_health
	target = player_target

func _ready() -> void:
	add_to_group("action_rpg_boss")
	collision_layer = 4
	collision_mask = 1 | 2
	var collision := CollisionShape2D.new()
	var shape := CircleShape2D.new()
	shape.radius = 27.0
	collision.shape = shape
	add_child(collision)
	var visual := Polygon2D.new()
	visual.polygon = PackedVector2Array([Vector2(-29, -31), Vector2(29, -31), Vector2(35, 20), Vector2(0, 35), Vector2(-35, 20)])
	visual.color = Color("a33b2f")
	add_child(visual)

func _physics_process(delta: float) -> void:
	if health <= 0 or not is_instance_valid(target):
		return
	attack_cooldown -= delta
	if telegraph_left > 0.0:
		state = "slam_telegraph"
		telegraph_left -= delta
		if telegraph_left <= 0.0 and global_position.distance_to(target.global_position) < 90.0:
			target.take_damage(1)
			state = "slam"
		return
	if attack_cooldown <= 0.0:
		telegraph_left = 0.55
		attack_cooldown = 1.8 if phase == 1 else 1.05
	else:
		state = "enraged" if phase == 2 else "idle"
		velocity = global_position.direction_to(target.global_position) * (42.0 if phase == 1 else 68.0)
		move_and_slide()

func take_damage(amount: int) -> bool:
	if amount <= 0 or health <= 0:
		return false
	health = maxi(0, health - amount)
	if phase == 1 and health <= max_health / 2:
		phase = 2
		state = "enraged"
		phase_changed.emit(phase)
	if health == 0:
		state = "defeated"
		collision_layer = 0
		collision_mask = 0
		defeated.emit()
	return true
