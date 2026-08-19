class_name SagaActionRpgPlayer
extends CharacterBody2D

signal swing_requested(origin: Vector2, facing: Vector2)
signal health_changed(current: int, maximum: int)
signal defeated

var move_speed := 180.0
var max_health := 5
var health := 5
var movement_locked := false
var dash_unlocked := false
var facing := Vector2.DOWN
var invulnerability_left := 0.0
var attack_cooldown_left := 0.0
var dash_cooldown_left := 0.0
var _attack_latched := false
var _dash_latched := false

func _ready() -> void:
	add_to_group("action_rpg_player")
	collision_layer = 2
	collision_mask = 1 | 4
	var collision := CollisionShape2D.new()
	var shape := CapsuleShape2D.new()
	shape.radius = 12.0
	shape.height = 28.0
	collision.shape = shape
	add_child(collision)
	if get_child_count() == 1:
		var body := Polygon2D.new()
		body.polygon = PackedVector2Array([Vector2(-12, -15), Vector2(12, -15), Vector2(14, 11), Vector2(0, 17), Vector2(-14, 11)])
		body.color = Color("f0a83b")
		add_child(body)

func _physics_process(delta: float) -> void:
	invulnerability_left = maxf(0.0, invulnerability_left - delta)
	attack_cooldown_left = maxf(0.0, attack_cooldown_left - delta)
	dash_cooldown_left = maxf(0.0, dash_cooldown_left - delta)
	var input_vector := Vector2.ZERO
	if not movement_locked and health > 0:
		input_vector = Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
	if input_vector.length_squared() > 0.0:
		facing = input_vector.normalized()
	var dash_pressed := Input.is_key_pressed(KEY_SHIFT)
	var dash_now := dash_unlocked and dash_pressed and not _dash_latched and dash_cooldown_left <= 0.0
	velocity = input_vector.normalized() * move_speed * (2.4 if dash_now else 1.0)
	if dash_now:
		dash_cooldown_left = 0.75
	move_and_slide()
	position.x = clampf(position.x, 34.0, 990.0)
	position.y = clampf(position.y, 92.0, 542.0)
	var pressed := Input.is_key_pressed(KEY_Z) or Input.is_action_pressed("ui_accept")
	if pressed and not _attack_latched:
		attack()
	_attack_latched = pressed
	_dash_latched = dash_pressed

func attack() -> bool:
	if movement_locked or health <= 0 or attack_cooldown_left > 0.0:
		return false
	attack_cooldown_left = 0.4
	swing_requested.emit(global_position, facing)
	return true

func take_damage(amount: int) -> bool:
	if amount <= 0 or health <= 0 or invulnerability_left > 0.0:
		return false
	health = maxi(0, health - amount)
	invulnerability_left = 1.0
	health_changed.emit(health, max_health)
	if health == 0:
		movement_locked = true
		defeated.emit()
	return true

func restore(full_health := true) -> void:
	health = max_health if full_health else maxi(1, health)
	movement_locked = false
	invulnerability_left = 0.0
	health_changed.emit(health, max_health)

func qa_nudge(direction: Vector2, distance := 24.0) -> float:
	var before := position
	facing = direction.normalized()
	position += facing * distance
	position.x = clampf(position.x, 34.0, 990.0)
	position.y = clampf(position.y, 92.0, 542.0)
	return before.distance_to(position)
