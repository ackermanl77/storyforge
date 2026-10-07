"""F9: explicit Tab / Shift+Tab order (app/ui_focus.py), tested with stand-in
widgets so it runs without a display."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ui_focus import _move_focus, apply_tab_order, focus_target


class FakeWidget:
    def __init__(self, name, viewable=True, state="normal", inner=None):
        self.name = name
        self.viewable = viewable
        self.state = state
        self.bindings = {}
        self.options = {}
        self.focused = False
        if inner is not None:
            self._textbox = inner

    def winfo_exists(self):
        return 1

    def winfo_viewable(self):
        return 1 if self.viewable else 0

    def cget(self, key):
        if key != "state":
            raise KeyError(key)
        return self.state

    def configure(self, **kwargs):
        self.options.update(kwargs)

    def bind(self, sequence, func):
        self.bindings[sequence] = func

    def focus_set(self):
        self.focused = True


class Container:
    pass


class TestTabOrder(unittest.TestCase):
    def test_focus_goes_to_the_inner_tk_widget(self):
        inner = FakeWidget("inner")
        self.assertIs(focus_target(FakeWidget("ctk", inner=inner)), inner)
        plain = FakeWidget("plain")
        self.assertIs(focus_target(plain), plain)

    def test_tab_and_shift_tab_follow_the_declared_order_and_wrap(self):
        a, b, c = FakeWidget("a"), FakeWidget("b"), FakeWidget("c")
        container = Container()
        order = apply_tab_order(container, a, [b, None], (c,))
        self.assertEqual(order, [a, b, c])
        self.assertIs(container._storyforge_tab_order, order)
        self.assertTrue(all(w.options.get("takefocus") for w in order))

        self.assertEqual(a.bindings["<Tab>"](None), "break")
        self.assertTrue(b.focused)
        c.bindings["<Tab>"](None)
        self.assertTrue(a.focused, "Tab on the last widget wraps to the first")
        a.focused = False
        a.bindings["<Shift-Tab>"](None)
        self.assertTrue(c.focused, "Shift+Tab on the first widget wraps to the last")

    def test_bindings_accept_being_called_without_an_event(self):
        # Regression: some CustomTkinter widgets invoke bound callbacks with no
        # event; the lambda required one and raised TypeError in the app.
        a, b = FakeWidget("a"), FakeWidget("b")
        apply_tab_order(Container(), a, b)
        self.assertEqual(a.bindings["<Tab>"](), "break")
        self.assertTrue(b.focused)

    def test_hidden_and_disabled_widgets_are_skipped(self):
        a = FakeWidget("a")
        hidden = FakeWidget("hidden", viewable=False)
        disabled = FakeWidget("disabled", state="disabled")
        d = FakeWidget("d")
        order = [a, hidden, disabled, d]
        _move_focus(order, 0, 1)
        self.assertTrue(d.focused)
        self.assertFalse(hidden.focused or disabled.focused)

    def test_nothing_focusable_does_not_raise(self):
        order = [FakeWidget("x", viewable=False)]
        self.assertEqual(_move_focus(order, 0, 1), "break")
        self.assertEqual(_move_focus([], 0, 1), "break")


if __name__ == "__main__":
    unittest.main()
