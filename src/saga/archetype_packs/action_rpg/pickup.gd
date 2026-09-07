class_name SagaActionRpgPickup
extends Area2D

signal collected(pickup_id: String, kind: String, amount: int)

var pickup_id := "pickup"
var kind := "sparks"
var amount := 1
var consumed := false

func _ready() -> void:
	add_to_group("action_rpg_pickups")
	collision_layer = 8
	collision_mask = 2
	var collision := CollisionShape2D.new()
	var shape := CircleShape2D.new()
	shape.radius = 12.0
	collision.shape = shape
	add_child(collision)
	var visual := Polygon2D.new()
	visual.name = "FallbackVisual"
	visual.polygon = PackedVector2Array([Vector2(0, -13), Vector2(11, 0), Vector2(0, 13), Vector2(-11, 0)])
	var colors := {"sparks": Color("ffd56b"), "health": Color("73e0b0"), "item": Color("a98beb")}
	visual.color = colors.get(kind, colors["item"])
	add_child(visual)
	body_entered.connect(_on_body_entered)

func _process(_delta: float) -> void:
	var sprite := get_node_or_null("AuthoredSprite") as Sprite2D
	if is_instance_valid(sprite):
		var phase := Time.get_ticks_msec() * 0.005 + float(get_instance_id() % 17)
		sprite.position.y = -6.0 + sin(phase) * 4.0
		sprite.rotation = sin(phase * 0.55) * 0.08

func configure(data: Dictionary) -> void:
	pickup_id = str(data.get("id", pickup_id))
	kind = str(data.get("kind", kind))
	amount = int(data.get("amount", amount))

func collect_for(player: Node) -> bool:
	if consumed or not player.is_in_group("action_rpg_player"):
		return false
	consumed = true
	visible = false
	# body_entered is emitted while physics is flushing queries. Changing an
	# Area2D's monitoring state synchronously from that callback is rejected by
	# Godot and used to turn an ordinary pickup into a runtime error.
	set_deferred("monitoring", false)
	collected.emit(pickup_id, kind, amount)
	return true

func _on_body_entered(body: Node) -> void:
	collect_for(body)
