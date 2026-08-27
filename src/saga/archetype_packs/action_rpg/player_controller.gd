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
var authored_sprite: Sprite2D
var idle_texture: Texture2D
var walk_texture: Texture2D
var authored_scale := Vector2.ONE
var animation_clock := 0.0
var attack_animation_left := 0.0
var hurt_animation_left := 0.0

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
		body.name = "FallbackVisual"
		body.polygon = PackedVector2Array([Vector2(-12, -15), Vector2(12, -15), Vector2(14, 11), Vector2(0, 17), Vector2(-14, 11)])
		body.color = Color("f0a83b")
		add_child(body)

func set_authored_visual(idle_path: String, walk_path: String, max_size := 58.0) -> bool:
	idle_texture = load(idle_path) as Texture2D if idle_path != "" else null
	walk_texture = load(walk_path) as Texture2D if walk_path != "" else null
	if idle_texture == null:
		return false
	for child in get_children():
		if child is Polygon2D:
			child.visible = false
	authored_sprite = Sprite2D.new()
	authored_sprite.name = "AuthoredSprite"
	authored_sprite.texture = idle_texture
	authored_scale = Vector2.ONE * minf(
		max_size / maxf(idle_texture.get_width(), 1),
		max_size / maxf(idle_texture.get_height(), 1)
	)
	authored_sprite.scale = authored_scale
	authored_sprite.position.y = -8.0
	authored_sprite.z_index = 2
	add_child(authored_sprite)
	return true

func _physics_process(delta: float) -> void:
	invulnerability_left = maxf(0.0, invulnerability_left - delta)
	attack_cooldown_left = maxf(0.0, attack_cooldown_left - delta)
	dash_cooldown_left = maxf(0.0, dash_cooldown_left - delta)
	attack_animation_left = maxf(0.0, attack_animation_left - delta)
	hurt_animation_left = maxf(0.0, hurt_animation_left - delta)
	animation_clock += delta
	var input_vector := Vector2.ZERO
	if not movement_locked and health > 0:
		input_vector = Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
	if input_vector.length_squared() > 0.0:
		facing = input_vector.normalized()
	var dash_pressed := Input.is_key_pressed(KEY_SHIFT) or Input.is_action_pressed("rpg_dash")
	var dash_now := dash_unlocked and dash_pressed and not _dash_latched and dash_cooldown_left <= 0.0
	velocity = input_vector.normalized() * move_speed * (2.4 if dash_now else 1.0)
	if dash_now:
		dash_cooldown_left = 0.75
		_spawn_dash_echo()
		Sfx.play("dash")
	move_and_slide()
	position.x = clampf(position.x, 34.0, 990.0)
	position.y = clampf(position.y, 92.0, 542.0)
	var pressed := Input.is_key_pressed(KEY_Z) or Input.is_action_pressed("rpg_attack")
	if pressed and not _attack_latched:
		attack()
	_attack_latched = pressed
	_dash_latched = dash_pressed
	_update_authored_animation(input_vector, dash_now)

func _update_authored_animation(input_vector: Vector2, dash_now: bool) -> void:
	if not is_instance_valid(authored_sprite):
		return
	var moving := input_vector.length_squared() > 0.01
	var stride := int(animation_clock / 0.11) % 2
	authored_sprite.texture = walk_texture if moving and walk_texture != null and stride == 1 else idle_texture
	authored_sprite.flip_h = facing.x > 0.12
	var target_position := Vector2(0, -8)
	var target_scale := authored_scale
	var target_rotation := 0.0
	if moving:
		target_position.y += sin(animation_clock * 18.0) * 2.5
		target_scale *= Vector2(1.0 + 0.04 * stride, 1.0 - 0.04 * stride)
		target_rotation = clampf(facing.x * 0.08, -0.08, 0.08)
	else:
		target_position.y += sin(animation_clock * 3.2) * 1.2
	if attack_animation_left > 0.0:
		var attack_phase := attack_animation_left / 0.18
		target_position += facing * (10.0 * sin(attack_phase * PI))
		target_rotation += facing.x * 0.24 * sin(attack_phase * PI)
		target_scale *= Vector2(1.12, 0.92)
	if dash_now:
		target_scale *= Vector2(1.22, 0.82)
	authored_sprite.position = authored_sprite.position.lerp(target_position, 0.45)
	authored_sprite.scale = authored_sprite.scale.lerp(target_scale, 0.45)
	authored_sprite.rotation = lerpf(authored_sprite.rotation, target_rotation, 0.4)
	authored_sprite.modulate = (
		Color(1.0, 0.42, 0.42, 1.0)
		if hurt_animation_left > 0.0 and int(hurt_animation_left * 30.0) % 2 == 0
		else Color.WHITE
	)

func _spawn_dash_echo() -> void:
	if not is_instance_valid(authored_sprite) or get_parent() == null:
		return
	var echo := Sprite2D.new()
	echo.texture = authored_sprite.texture
	echo.flip_h = authored_sprite.flip_h
	echo.global_position = global_position + authored_sprite.position
	echo.scale = authored_sprite.scale
	echo.modulate = Color(0.35, 0.9, 1.0, 0.48)
	echo.z_index = 1
	get_parent().add_child(echo)
	var tween := echo.create_tween()
	tween.set_parallel(true)
	tween.tween_property(echo, "modulate:a", 0.0, 0.22)
	tween.tween_property(echo, "scale", echo.scale * 1.18, 0.22)
	tween.chain().tween_callback(echo.queue_free)

func attack() -> bool:
	if movement_locked or health <= 0 or attack_cooldown_left > 0.0:
		return false
	attack_cooldown_left = 0.4
	attack_animation_left = 0.18
	Sfx.play("swing")
	swing_requested.emit(global_position, facing)
	return true

func take_damage(amount: int) -> bool:
	if amount <= 0 or health <= 0 or invulnerability_left > 0.0:
		return false
	health = maxi(0, health - amount)
	invulnerability_left = 1.0
	hurt_animation_left = 0.32
	Sfx.play("hit")
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
