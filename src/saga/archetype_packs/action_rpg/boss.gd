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
var animation_clock := 0.0
var authored_sprite: Sprite2D
var authored_base_scale := Vector2.ONE
var telegraph: Polygon2D
var health_fill: Polygon2D

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
	visual.name = "FallbackVisual"
	visual.polygon = PackedVector2Array([Vector2(-29, -31), Vector2(29, -31), Vector2(35, 20), Vector2(0, 35), Vector2(-35, 20)])
	visual.color = Color("a33b2f")
	add_child(visual)
	telegraph = Polygon2D.new()
	telegraph.name = "SlamTelegraph"
	telegraph.z_index = -1
	telegraph.visible = false
	var ring := PackedVector2Array()
	for index in range(28):
		var angle := TAU * float(index) / 28.0
		ring.append(Vector2(cos(angle), sin(angle)) * 86.0)
	telegraph.polygon = ring
	telegraph.color = Color(1.0, 0.16, 0.08, 0.24)
	add_child(telegraph)
	var back := Polygon2D.new()
	back.position = Vector2(-46, -50)
	back.polygon = PackedVector2Array([Vector2(0, 0), Vector2(92, 0), Vector2(92, 7), Vector2(0, 7)])
	back.color = Color(0.02, 0.025, 0.035, 0.9)
	back.z_index = 8
	add_child(back)
	health_fill = Polygon2D.new()
	health_fill.position = Vector2(-44, -48)
	health_fill.polygon = PackedVector2Array([Vector2(0, 0), Vector2(88, 0), Vector2(88, 3), Vector2(0, 3)])
	health_fill.color = Color("f05d45")
	health_fill.z_index = 9
	add_child(health_fill)

func _physics_process(delta: float) -> void:
	if health <= 0 or not is_instance_valid(target):
		return
	animation_clock += delta
	_find_authored_sprite()
	attack_cooldown -= delta
	if telegraph_left > 0.0:
		state = "slam_telegraph"
		telegraph.visible = true
		telegraph.scale = Vector2.ONE * (0.84 + 0.16 * (1.0 - telegraph_left / 0.55))
		telegraph_left -= delta
		if telegraph_left <= 0.0:
			telegraph.visible = false
			if global_position.distance_to(target.global_position) < 90.0:
				target.take_damage(1)
			state = "slam"
		_update_visual()
		return
	if attack_cooldown <= 0.0:
		telegraph_left = 0.55
		attack_cooldown = 1.8 if phase == 1 else 1.05
	else:
		state = "enraged" if phase == 2 else "idle"
		velocity = global_position.direction_to(target.global_position) * (42.0 if phase == 1 else 68.0)
		move_and_slide()
	_update_visual()

func _find_authored_sprite() -> void:
	if not is_instance_valid(authored_sprite):
		authored_sprite = get_node_or_null("AuthoredSprite") as Sprite2D
		if is_instance_valid(authored_sprite):
			authored_base_scale = authored_sprite.scale

func _update_visual() -> void:
	if not is_instance_valid(authored_sprite):
		return
	var pulse := sin(animation_clock * (6.5 if phase == 2 else 3.5))
	authored_sprite.position.y = -6.0 + pulse * 2.0
	authored_sprite.scale = authored_base_scale * (1.0 + pulse * (0.05 if phase == 2 else 0.025))
	authored_sprite.modulate = Color(1.0, 0.72, 0.62, 1.0) if state == "slam_telegraph" else Color.WHITE

func take_damage(amount: int) -> bool:
	if amount <= 0 or health <= 0:
		return false
	health = maxi(0, health - amount)
	if is_instance_valid(health_fill):
		health_fill.scale.x = float(health) / float(maxi(max_health, 1))
	_find_authored_sprite()
	if is_instance_valid(authored_sprite):
		var flash := authored_sprite.create_tween()
		flash.tween_property(authored_sprite, "modulate", Color.WHITE * 2.2, 0.04)
		flash.tween_property(authored_sprite, "modulate", Color.WHITE, 0.16)
	if phase == 1 and health <= max_health / 2:
		phase = 2
		state = "enraged"
		phase_changed.emit(phase)
	if health == 0:
		state = "defeated"
		collision_layer = 0
		collision_mask = 0
		defeated.emit()
		var death := create_tween()
		death.set_parallel(true)
		death.tween_property(self, "scale", Vector2(1.65, 0.25), 0.42)
		death.tween_property(self, "modulate:a", 0.0, 0.42)
	return true
