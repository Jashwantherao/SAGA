class_name SagaActionRpgInventory
extends RefCounted

var sparks := 0
var items: Dictionary = {}

func add_sparks(amount: int) -> void:
	sparks = maxi(0, sparks + amount)

func spend_sparks(amount: int) -> bool:
	if amount < 0 or sparks < amount:
		return false
	sparks -= amount
	return true

func add_item(item_id: String, amount := 1) -> void:
	if item_id == "" or amount <= 0:
		return
	items[item_id] = int(items.get(item_id, 0)) + amount

func count(item_id: String) -> int:
	return int(items.get(item_id, 0))

func snapshot() -> Dictionary:
	return {"sparks": sparks, "items": items.duplicate(true)}

func restore(data: Dictionary) -> void:
	sparks = maxi(0, int(data.get("sparks", 0)))
	items = (data.get("items", {}) as Dictionary).duplicate(true)
