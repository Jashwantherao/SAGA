class_name SagaRunAndGunProjectile
extends Area2D

var direction := Vector2.RIGHT
var speed := 700.0
var damage := 1
var faction := "player"
var lifetime := 2.5
var blast_radius := 0.0
var weapon_id := "pulse"
var visual: Polygon2D

func _ready() -> void:
	add_to_group("run_and_gun_projectiles")
	collision_layer = 4 if faction == "player" else 8
	collision_mask = 2 if faction == "player" else 1
	var shape := CollisionShape2D.new()
	var rectangle := RectangleShape2D.new()
	rectangle.size = Vector2(18, 8)
	shape.shape = rectangle
	add_child(shape)
	visual = Polygon2D.new()
	visual.polygon = PackedVector2Array([
		Vector2(-9, -4), Vector2(9, -4), Vector2(9, 4), Vector2(-9, 4)
	])
	visual.color = Color("70f4ff") if faction == "player" else Color("ff685f")
	add_child(visual)
	body_entered.connect(_on_body_entered)

func configure(options: Dictionary) -> void:
	direction = Vector2(options.get("direction", Vector2.RIGHT)).normalized()
	speed = float(options.get("speed", speed))
	damage = int(options.get("damage", damage))
	blast_radius = float(options.get("blast_radius", blast_radius))
	weapon_id = str(options.get("weapon_id", weapon_id))
	faction = str(options.get("faction", faction))
	collision_layer = 4 if faction == "player" else 8
	collision_mask = 2 if faction == "player" else 1
	if is_instance_valid(visual):
		visual.color = Color("ffb34f") if weapon_id == "launcher" else (Color("fff46b") if weapon_id == "spread" else (Color("70f4ff") if faction == "player" else Color("ff685f")))
		if weapon_id == "launcher":
			visual.scale = Vector2(1.5, 1.5)

func _physics_process(delta: float) -> void:
	global_position += direction * speed * delta
	lifetime -= delta
	if lifetime <= 0.0 or abs(global_position.x) > 5000.0:
		queue_free()

func _on_body_entered(body: Node) -> void:
	if body.get("faction") == faction:
		return
	if body.has_method("take_damage"):
		body.take_damage(damage)
	if blast_radius > 0.0 and faction == "player":
		for candidate in get_tree().get_nodes_in_group("run_and_gun_enemies"):
			if candidate != body and is_instance_valid(candidate) and candidate.has_method("take_damage") and global_position.distance_to(candidate.global_position) <= blast_radius:
				candidate.take_damage(damage)
	queue_free()
