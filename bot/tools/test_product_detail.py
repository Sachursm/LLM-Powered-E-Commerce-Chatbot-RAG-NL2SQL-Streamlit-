"""Rules that turn "the 2nd one" / "product 812" into a product ID."""

import unittest

from bot.tools.product_detail import first_position, remember_shown, resolve_product_reference, shown_entries, shown_ids

SHOWN = [812, 455, 90, 31, 7]


class ResolveProductReferenceTests(unittest.TestCase):
    def check(self, text, kind, product_id=None, position=None, shown=SHOWN):
        ref = resolve_product_reference(text, shown)
        self.assertEqual((ref.kind, ref.product_id, ref.position), (kind, product_id, position), text)
        return ref

    def test_positions_in_the_list(self):
        self.check("show me the first product", "id", 812, 1)
        self.check("tell me more about the 2nd one", "id", 455, 2)
        self.check("open the last one", "id", 7, 5)
        self.check("details of number 3", "id", 90, 3)

    def test_explicit_ids(self):
        self.check("details of product id 45", "id", 45)
        self.check("give me full details of #455", "id", 455)
        self.check("product id 2", "id", 2)

    def test_bare_number_on_the_list_is_that_id(self):
        self.check("show product 812", "id", 812)

    def test_bare_number_past_the_list_is_an_id(self):
        self.check("show product 40", "id", 40)

    def test_bare_number_that_could_be_either_asks(self):
        ref = self.check("what is the description of product 2", "ambiguous", 2, 2)
        self.assertEqual(ref.list_id, 455)

    def test_no_product_named_asks(self):
        self.check("show me more about that boot", "ask")

    def test_position_past_the_list(self):
        self.check("the 9th one", "out_of_range", None, 9)

    def test_position_without_a_list(self):
        self.check("the first one", "need_list", None, 1, shown=[])
        self.check("show product 2", "id", 2, shown=[])


class ShownIdsTests(unittest.TestCase):
    def test_new_search_replaces_and_show_more_extends(self):
        first = remember_shown([1, 2], 0, [10, 11])
        self.assertEqual(first, [10, 11])
        self.assertEqual(remember_shown(first, 2, [12]), [10, 11, 12])
        self.assertEqual(first_position(2, first), 3)

    def test_entries_keep_id_and_name(self):
        entries = shown_entries([{"id": 21, "name": "Infant Bodysuit"}, {"name": "no id"}])
        self.assertEqual(entries, [{"id": 21, "name": "Infant Bodysuit"}])
        self.assertEqual(shown_ids({"shown_products": entries}), [21])

    def test_unknown_earlier_pages_restart_numbering(self):
        self.assertEqual(remember_shown(None, 5, [12]), [12])
        self.assertEqual(first_position(5, None), 1)


if __name__ == "__main__":
    unittest.main()
