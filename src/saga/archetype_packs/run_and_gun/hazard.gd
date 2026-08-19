class_name SagaRunAndGunHazard
extends Area2D

var damage := 1
var damage_interval := 0.85
var _touching: Array[Node] = []
var _cooldowns: Dictionary = {}

func _ready() -> void:
	add_to_group("run_and_gun_hazards")
	collision_layer = 0
	collision_mask = 1
	body_entered.connect(_on_body_entered)
	body_exited.connect(_on_body_exited)

func _physics_process(delta: float) -> void:
	for body in _touching.duplicate():
		if not is_instance_valid(body):
			_touching.erase(body)
			continue
		var key: int = body.get_instance_id()
		var remaining := maxf(0.0, float(_cooldowns.get(key, 0.0)) - delta)
		_cooldowns[key] = remaining
		if remaining <= 0.0:
			_damage(body)

func configure(options: Dictionary) -> void:
	damage = int(options.get("damage", damage))
	var size := Vector2(float(options.get("width", 80.0)), 24.0)
	var collision := CollisionShape2D.new()
	var rectangle := RectangleShape2D.new()
	rectangle.size = size
	collision.shape = rectangle
	add_child(collision)
	# House the damage area in a powered deck unit so the hazard reads as an
	# authored object, rather than a pair of disconnected debug triangles.
	_add_panel(PackedVector2Array([
		Vector2(-size.x / 2.0 - 6, 7), Vector2(size.x / 2.0 + 6, 7),
		Vector2(size.x / 2.0, 16), Vector2(-size.x / 2.0, 16),
	]), Color("111a31"))
	_add_panel(PackedVector2Array([
		Vector2(-size.x / 2.0, 5), Vector2(size.x / 2.0, 5),
		Vector2(size.x / 2.0, 10), Vector2(-size.x / 2.0, 10),
	]), Color("ff9c3d"))
	var spike_count := maxi(3, int(size.x / 24.0))
	var step := size.x / float(spike_count)
	for index in range(spike_count):
		var left := -size.x / 2.0 + step * index + 2.0
		var right := left + step - 4.0
		_add_panel(PackedVector2Array([
			Vector2(left, 5), Vector2((left + right) / 2.0, -12), Vector2(right, 5),
		]), Color("ff4f5e"))
	var energy := Line2D.new()
	energy.width = 2.0
	energy.default_color = Color("ffe36b")
	var energy_points := PackedVector2Array()
	for index in range(spike_count * 2 + 1):
		energy_points.append(Vector2(
			-size.x / 2.0 + size.x * float(index) / float(spike_count * 2),
			-2.0 if index % 2 == 0 else -8.0
		))
	energy.points = energy_points
	add_child(energy)

func _add_panel(points: PackedVector2Array, color: Color) -> void:
	var panel := Polygon2D.new()
	panel.polygon = points
	panel.color = color
	add_child(panel)

func _on_body_entered(body: Node) -> void:
	if body.has_method("take_damage") and body.is_in_group("run_and_gun_player"):
		_touching.append(body)
		_damage(body)

func _on_body_exited(body: Node) -> void:
	_touching.erase(body)
	_cooldowns.erase(body.get_instance_id())

func _damage(body: Node) -> void:
	if not is_instance_valid(body):
		return
	body.take_damage(damage)
	_cooldowns[body.get_instance_id()] = damage_interval
