import random

from synthetic.names import (
    generate_carrier_names,
    generate_customer_names,
    generate_phone_number,
    generate_unique_number,
)


class TestGenerateCarrierNames:
    def test_returns_requested_count_all_unique(self):
        rng = random.Random(42)
        names = generate_carrier_names(rng, 30)
        assert len(names) == 30
        assert len(set(names)) == 30

    def test_deterministic_given_same_seed(self):
        names_a = generate_carrier_names(random.Random(42), 30)
        names_b = generate_carrier_names(random.Random(42), 30)
        assert names_a == names_b  # exact order, not just same set

    def test_different_seeds_produce_different_output(self):
        names_a = generate_carrier_names(random.Random(1), 30)
        names_b = generate_carrier_names(random.Random(2), 30)
        assert names_a != names_b


class TestGenerateCustomerNames:
    def test_returns_requested_count_all_unique(self):
        rng = random.Random(7)
        names = generate_customer_names(rng, 20)
        assert len(names) == 20
        assert len(set(names)) == 20

    def test_deterministic_given_same_seed(self):
        names_a = generate_customer_names(random.Random(7), 20)
        names_b = generate_customer_names(random.Random(7), 20)
        assert names_a == names_b


class TestGenerateUniqueNumber:
    def test_avoids_collisions_with_used_set(self):
        rng = random.Random(3)
        used: set[str] = set()
        numbers = [generate_unique_number(rng, used, 1, 5) for _ in range(5)]
        # Forces every value in [1,5] to be drawn exactly once -- proves
        # the uniqueness constraint is actually enforced, not just
        # statistically unlikely to collide.
        assert sorted(numbers) == ["1", "2", "3", "4", "5"]

    def test_deterministic_given_same_seed_and_fresh_used_set(self):
        a = generate_unique_number(random.Random(9), set(), 100000, 999999)
        b = generate_unique_number(random.Random(9), set(), 100000, 999999)
        assert a == b


class TestGeneratePhoneNumber:
    def test_returns_ten_digit_string(self):
        rng = random.Random(11)
        phone = generate_phone_number(rng)
        assert len(phone) == 10
        assert phone.isdigit()

    def test_deterministic_given_same_seed(self):
        assert generate_phone_number(random.Random(11)) == generate_phone_number(random.Random(11))
