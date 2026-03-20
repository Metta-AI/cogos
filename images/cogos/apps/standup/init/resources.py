add_resource(
    "lambda_slots",
    type="pool",
    capacity=5,
    metadata={"description": "Concurrent Lambda executor slots"},
)
