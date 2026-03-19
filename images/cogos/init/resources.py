add_resource("lambda_slots", type="pool", capacity=5, metadata={"description": "Concurrent Lambda executor slots"})
add_resource("ecs_slots", type="pool", capacity=2, metadata={"description": "Concurrent ECS task slots"})
