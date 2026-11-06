
def java_string_hashcode(value: str) -> int:
    """
    Reproduces Java String.hashCode() using UTF-16 code units.
    """
    encoded = value.encode("utf-16-be")

    hash_value = 0

    for i in range(0, len(encoded), 2):
        char = int.from_bytes(encoded[i:i + 2], "big")
        hash_value = (31 * hash_value + char) & 0xFFFFFFFF

    # Convert to signed 32-bit integer
    if hash_value >= 0x80000000:
        hash_value -= 0x100000000

    return hash_value


def kafka_partition(key: str, partitions: int) -> int:
    """
    Reproduces Kafka's default partition calculation
    for a Java String key.
    """
    if partitions <= 0:
        raise ValueError("Partitions must be greater than zero")

    hash_value = java_string_hashcode(key)

    # Kafka's Utils.toPositive()
    positive_hash = hash_value & 0x7FFFFFFF

    return positive_hash % partitions


if __name__ == "__main__":
    request_ids = [
        "550e8400-e29b-41d4-a716-446655440000",
        "550e8400-e29b-41d4-a716-446655440001",
        "550e8400-e29b-41d4-a716-446655440002",
    ]

    partitions = 6

    for request_id in request_ids:
        print(
            f"Request ID: {request_id} "
            f"-> Partition: {kafka_partition(request_id, partitions)}"
        )
