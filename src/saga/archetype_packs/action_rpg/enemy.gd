class_name SagaActionRpgEnemy
extends CharacterBody2D

signal defeated(enemy_id: String)

var enemy_id := "enemy"
var enemy_name := "Enemy"
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
var orbit_direction := 1.0
var windup_left := 0.0
var windup_duration := 0.32
var attack_reach := 42.0
var animation_clock := 0.0
var authored_sprite: Sprite2D
var authored_base_scale := Vector2.ONE
var telegraph: Polygon2D
var health_fill: Polygon2D

func _ready() -> void:
	add_to_group("action_rpg_enemies")
	collision_layer = 4
	collision_mask = 1 | 2
	home = position
	var collision := CollisionShape2D.new()
	var shape := CircleShape2D.new()
	shape.radius = 17.0 if role == "bruiser" else 13.0
	collision.shape = shape
	add_child(collision)
	var visual := Polygon2D.new()
	visual.name = "FallbackVisual"
	var role_shapes := {
		"stalker": PackedVector2Array([Vector2(-14, -10), Vector2(10, -14), Vector2(16, 4), Vector2(5, 14), Vector2(-15, 10)]),
		"skirmisher": PackedVector2Array([Vector2(0, -17), Vector2(16, 0), Vector2(0, 12), Vector2(-16, 0)]),
		"sentinel": PackedVector2Array([Vector2(-15, -15), Vector2(15, -15), Vector2(18, 10), Vector2(0, 17), Vector2(-18, 10)]),
		"bruiser": PackedVector2Array([Vector2(-20, -14), Vector2(16, -18), Vector2(22, 4), Vector2(10, 20), Vector2(-20, 15)])
	}
	var role_colors := {
		"stalker": Color("d45b4e"), "skirmisher": Color("d79b45"),
		"sentinel": Color("6f8dd8"), "bruiser": Color("9b5975")
	}
	visual.polygon = role_shapes.get(role, role_shapes["stalker"])
	visual.color = role_colors.get(role, role_colors["stalker"])
	add_child(visual)
	var name_label := Label.new()
	name_label.text = enemy_name
	name_label.position = Vector2(-65, -45)
	name_label.size = Vector2(130, 18)
	name_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	name_label.add_theme_font_size_override("font_size", 10)
	name_label.z_index = 9
	add_child(name_label)
	telegraph = Polygon2D.new()
	telegraph.name = "AttackTelegraph"
	telegraph.z_index = -1
	telegraph.visible = false
	var telegraph_points := PackedVector2Array()
	for index in range(20):
		var angle := TAU * float(index) / 20.0
		telegraph_points.append(Vector2(cos(angle), sin(angle)) * (24.0 if role != "bruiser" else 32.0))
	telegraph.polygon = telegraph_points
	telegraph.color = Color(1.0, 0.2, 0.12, 0.28)
	add_child(telegraph)
	_build_health_bar()

func _build_health_bar() -> void:
	var back := Polygon2D.new()
	back.name = "HealthBack"
	back.position = Vector2(-18, -27)
	back.polygon = PackedVector2Array([Vector2(0, 0), Vector2(36, 0), Vector2(36, 4), Vector2(0, 4)])
	back.color = Color(0.03, 0.04, 0.05, 0.82)
	back.z_index = 7
	add_child(back)
	health_fill = Polygon2D.new()
	health_fill.name = "HealthFill"
	health_fill.position = Vector2(-17, -26)
	health_fill.polygon = PackedVector2Array([Vector2(0, 0), Vector2(34, 0), Vector2(34, 2), Vector2(0, 2)])
	health_fill.color = Color("e65b4d")
	health_fill.z_index = 8
	add_child(health_fill)

func configure(data: Dictionary, player_target: SagaActionRpgPlayer) -> void:
	enemy_id = str(data.get("id", enemy_id))
	enemy_name = str(data.get("name", enemy_name))
	role = str(data.get("role", role))
	max_health = int(data.get("health", max_health))
	health = max_health
	move_speed = float(data.get("speed", move_speed))
	if role == "bruiser":
		move_speed *= 0.68
		attack_radius = 42.0
	elif role == "skirmisher":
		move_speed *= 1.25
		detection_radius = 285.0
	elif role == "sentinel":
		move_speed *= 0.82
		detection_radius = 190.0
	orbit_direction = -1.0 if enemy_id.hash() % 2 == 0 else 1.0
	windup_duration = 0.48 if role == "bruiser" else (0.24 if role == "skirmisher" else 0.32)
	attack_reach = 175.0 if role == "skirmisher" else attack_radius + 12.0
	target = player_target

func _physics_process(delta: float) -> void:
	if health <= 0 or not is_instance_valid(target):
		velocity = Vector2.ZERO
		return
	stagger_left = maxf(0.0, stagger_left - delta)
	attack_cooldown = maxf(0.0, attack_cooldown - delta)
	animation_clock += delta
	_find_authored_sprite()
	if stagger_left > 0.0:
		state = "staggered"
		velocity = Vector2.ZERO
		move_and_slide()
		_update_visuals()
		return
	var distance := global_position.distance_to(target.global_position)
	if windup_left > 0.0:
		state = "attack_telegraph"
		velocity = Vector2.ZERO
		windup_left = maxf(0.0, windup_left - delta)
		telegraph.visible = true
		telegraph.scale = Vector2.ONE * (1.0 + 0.22 * sin(animation_clock * 24.0))
		if windup_left <= 0.0:
			telegraph.visible = false
			if global_position.distance_to(target.global_position) <= attack_reach:
				target.take_damage(2 if role == "bruiser" else 1)
			attack_cooldown = 1.65 if role == "bruiser" else (1.8 if role == "skirmisher" else 1.2)
		_update_visuals()
		return
	if distance <= attack_radius and role != "skirmisher":
		state = "threaten"
		velocity = Vector2.ZERO
		if attack_cooldown <= 0.0:
			windup_left = windup_duration
	elif distance <= detection_radius:
		if role == "skirmisher":
			state = "orbit"
			var toward := global_position.direction_to(target.global_position)
			if distance < 105.0:
				velocity = -toward * move_speed
			elif distance > 175.0:
				velocity = toward * move_speed
			else:
				velocity = Vector2(-toward.y, toward.x) * move_speed * orbit_direction
			if distance <= 155.0 and attack_cooldown <= 0.0:
				windup_left = windup_duration
		elif role == "sentinel" and distance > 118.0:
			state = "guard"
			velocity = global_position.direction_to(target.global_position) * move_speed * 0.5
		else:
			state = "chase"
			velocity = global_position.direction_to(target.global_position) * move_speed
	else:
		state = "patrol"
		patrol_offset += delta * 1.3
		var patrol_target := home + Vector2(sin(patrol_offset) * 55.0, 0.0)
		velocity = global_position.direction_to(patrol_target) * move_speed * 0.45
	move_and_slide()
	_update_visuals()

func _find_authored_sprite() -> void:
	if not is_instance_valid(authored_sprite):
		authored_sprite = get_node_or_null("AuthoredSprite") as Sprite2D
		if is_instance_valid(authored_sprite):
			authored_base_scale = authored_sprite.scale

func _update_visuals() -> void:
	if not is_instance_valid(authored_sprite):
		return
	var moving := velocity.length_squared() > 1.0
	var bob := sin(animation_clock * (12.0 if moving else 3.0)) * (2.0 if moving else 0.8)
	authored_sprite.position.y = -6.0 + bob
	authored_sprite.rotation = clampf(velocity.x / maxf(move_speed, 1.0) * 0.08, -0.1, 0.1)
	authored_sprite.flip_h = velocity.x > 1.0
	if state == "attack_telegraph":
		authored_sprite.modulate = Color(1.0, 0.48, 0.32, 1.0)
		authored_sprite.scale = authored_base_scale * (1.0 + 0.08 * sin(animation_clock * 18.0))
	else:
		authored_sprite.modulate = Color.WHITE
		authored_sprite.scale = authored_base_scale

func take_damage(amount: int, knockback := Vector2.ZERO) -> bool:
	if health <= 0 or amount <= 0:
		return false
	health = maxi(0, health - amount)
	stagger_left = 0.5
	state = "staggered"
	velocity = knockback
	if is_instance_valid(health_fill):
		health_fill.scale.x = float(health) / float(maxi(max_health, 1))
	_find_authored_sprite()
	if is_instance_valid(authored_sprite):
		var flash := authored_sprite.create_tween()
		flash.tween_property(authored_sprite, "modulate", Color.WHITE * 2.2, 0.04)
		flash.tween_property(authored_sprite, "modulate", Color.WHITE, 0.16)
	if health == 0:
		state = "defeated"
		collision_layer = 0
		collision_mask = 0
		defeated.emit(enemy_id)
		var death := create_tween()
		death.set_parallel(true)
		death.tween_property(self, "scale", Vector2(1.35, 0.35), 0.22)
		death.tween_property(self, "modulate:a", 0.0, 0.22)
		death.chain().tween_callback(queue_free)
	return true
