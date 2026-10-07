from datetime import datetime

from fileflow.core.categorizer import CustomRule
from fileflow.core.planner import build_plan, format_preview, resolve_conflicts, summarize
from fileflow.core.scanner import scan_folder
from tests.helpers import TmpCase


class PlannerTests(TmpCase):
    def plan(self, **kw):
        return build_plan(scan_folder(self.root), **kw)

    def test_spec_example(self):
        for n in ("IMG_39482.jpg", "invoice-final.pdf", "project_notes.txt", "vacation.jpg"):
            self.make(n, n)
        items = {i.src.name: i for i in self.plan(suggest_renames=False)}
        rel = lambda i: i.dst.relative_to(self.root).as_posix()
        self.assertEqual(rel(items["invoice-final.pdf"]), "Documents/Finance/Invoices/invoice-final.pdf")
        self.assertEqual(rel(items["vacation.jpg"]), "Pictures/Vacation/vacation.jpg")
        self.assertEqual(rel(items["project_notes.txt"]), "Projects/Notes/project_notes.txt")
        self.assertTrue(rel(items["IMG_39482.jpg"]).startswith("Pictures/"))

    def test_planning_touches_nothing(self):
        self.make("invoice.pdf")
        self.make("a.jpg")
        before = self.snapshot()
        self.plan()
        self.assertEqual(before, self.snapshot())

    def test_destination_collisions_get_unique_names(self):
        self.make("one/invoice.pdf", "A")
        self.make("two/invoice.pdf", "B")
        items = self.plan(scope="all", suggest_renames=False)
        dsts = {i.dst.name for i in items}
        self.assertEqual(dsts, {"invoice.pdf", "invoice (1).pdf"})

    def test_existing_destination_never_targeted(self):
        self.make("Documents/Finance/Invoices/invoice.pdf", "already here")
        self.make("invoice.pdf", "new")
        items = self.plan(suggest_renames=False)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].dst.name, "invoice (1).pdf")

    def test_already_organized_files_skipped(self):
        self.make("Documents/Finance/Invoices/invoice.pdf")
        self.assertEqual(self.plan(scope="all", suggest_renames=False), [])

    def test_scope_loose_ignores_subfolders(self):
        self.make("loose.pdf")
        self.make("sub/nested.pdf")
        names = {i.src.name for i in self.plan(scope="loose")}
        self.assertEqual(names, {"loose.pdf"})

    def test_project_and_hidden_files_ignored(self):
        self.make("proj/package.json")
        self.make("proj/readme.txt")
        self.make(".hidden.txt")
        self.assertEqual(self.plan(scope="all"), [])

    def test_custom_rule_and_rename_only_action(self):
        self.make("acme-notes.txt")
        items = self.plan(rules=[CustomRule("acme", ("Work", "Acme"))])
        self.assertEqual(items[0].dst.relative_to(self.root).as_posix(), "Work/Acme/acme-notes.txt")
        self.make("Copy of thing.zip")
        names = {i.src.name: i for i in self.plan()}
        self.assertEqual(names["Copy of thing.zip"].dst.name, "thing.zip")

    def test_summary_and_preview_format(self):
        self.make("invoice-final.pdf")
        self.make("vacation.jpg")
        items = self.plan(suggest_renames=False)
        self.assertEqual(summarize(items), "2 files will be moved")
        text = format_preview(items, self.root)
        self.assertIn("invoice-final.pdf\n→ Documents/Finance/Invoices/", text)
        self.assertIn("vacation.jpg\n→ Pictures/Vacation/", text)
        items[0].enabled = False
        self.assertEqual(summarize(items), "1 file will be moved")

    def test_edit_then_resolve_keeps_unique(self):
        self.make("a.pdf")
        self.make("b.pdf")
        items = self.plan(suggest_renames=False)
        items[1].dst = items[0].dst  # user edit creating a clash
        resolve_conflicts(items)
        self.assertNotEqual(items[0].dst, items[1].dst)
