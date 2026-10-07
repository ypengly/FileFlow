import unittest
from datetime import datetime
from pathlib import Path

from fileflow.core.categorizer import CustomRule, classify
from fileflow.core.renamer import suggest_name, tidy

WHEN = datetime(2026, 9, 28, 10, 11, 12)


def cls(name, rules=(), parent="Downloads"):
    return classify(Path("/x") / parent / name, WHEN, rules)


class CategorizerTests(unittest.TestCase):
    def test_examples_from_spec(self):
        self.assertEqual(cls("invoice-final.pdf").parts, ("Documents", "Finance", "Invoices"))
        self.assertEqual(cls("vacation.jpg").parts, ("Pictures", "Vacation"))
        self.assertEqual(cls("project_notes.txt").parts, ("Projects", "Notes"))

    def test_type_fallbacks(self):
        self.assertEqual(cls("IMG_1.jpg").parts, ("Pictures", "2026"))
        self.assertEqual(cls("song.mp3").parts, ("Audio",))
        self.assertEqual(cls("clip.mp4").parts, ("Videos",))
        self.assertEqual(cls("app.py").parts, ("Code", "Python"))
        self.assertEqual(cls("x.zip").parts, ("Archives",))
        c = cls("mystery.xyz")
        self.assertEqual(c.parts, ("Other",))
        self.assertTrue(c.fallback)

    def test_word_boundaries(self):
        self.assertNotEqual(cls("billboard.pdf").parts, ("Documents", "Finance", "Invoices"))

    def test_school_and_work(self):
        self.assertEqual(cls("math_homework.docx").category, "School")
        self.assertEqual(cls("my-resume.pdf").category, "Work")

    def test_custom_rule_wins(self):
        r = CustomRule("acme", ("Work", "Acme"))
        self.assertEqual(cls("acme-invoice.pdf", [r]).parts, ("Work", "Acme"))

    def test_images_in_travel_folder(self):
        self.assertEqual(cls("a.jpg", parent="Cambodia Trip").parts, ("Pictures", "Vacation"))


class RenamerTests(unittest.TestCase):
    def test_camera_name_gets_date_and_folder_label(self):
        new, _ = suggest_name(Path("/x/Cambodia Trip/IMG_9382.JPG"), WHEN)
        self.assertEqual(new, "2026-09-28_Cambodia_Trip_9382.jpg")

    def test_generic_folder_uses_photo(self):
        new, _ = suggest_name(Path("/x/Downloads/IMG_9382.jpg"), WHEN)
        self.assertEqual(new, "2026-09-28_Photo_9382.jpg")

    def test_screenshot(self):
        new, _ = suggest_name(Path("/x/Screenshot 2026-09-01 at 3.04.png"), WHEN)
        self.assertEqual(new, "2026-09-28_Screenshot_101112.png")

    def test_clean_names_left_alone(self):
        self.assertIsNone(suggest_name(Path("/x/invoice-final.pdf"), WHEN))

    def test_tidy(self):
        self.assertEqual(tidy("Copy of report"), "report")
        self.assertEqual(tidy("report - Copy"), "report")
        self.assertEqual(tidy("a__b"), "a_b")
