class_name SagaActionRpgNpc
extends Node2D

var npc_id := "hermit"
var speaker_name := "Ember Hermit"
var lines: Array[String] = [
	"The forge is fading.",
	"Bring me ten sparks and I will open the sealed road.",
	"Your lantern remembers how to dash."
]

func _ready() -> void:
	add_to_group("action_rpg_npcs")
	var visual := Polygon2D.new()
	visual.polygon = PackedVector2Array([Vector2(-14, -20), Vector2(14, -20), Vector2(19, 18), Vector2(-19, 18)])
	visual.color = Color("6b5a88")
	add_child(visual)
	var name_label := Label.new()
	name_label.text = speaker_name
	name_label.position = Vector2(-42, -43)
	name_label.add_theme_font_size_override("font_size", 11)
	add_child(name_label)
