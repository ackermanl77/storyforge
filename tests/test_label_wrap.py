"""Las etiquetas con wraplength fijo se ajustan al ancho de su contenedor (UI4)."""
import unittest

try:
    import customtkinter as ctk

    from app.ui_common import fit_label_wrap

    GUI_AVAILABLE = True
except Exception:  # pragma: no cover - sin customtkinter
    GUI_AVAILABLE = False


@unittest.skipUnless(GUI_AVAILABLE, "GUI no disponible")
class LabelWrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # La ventana se crea aqui (no al importar) y se destruye al terminar, para no
        # dejar una raiz de Tk extra viva durante las pruebas de los otros modulos.
        try:
            cls.root = ctk.CTk()
        except Exception as exc:  # pragma: no cover - sin pantalla
            raise unittest.SkipTest(f"sin pantalla: {exc}")
        cls.root.attributes("-alpha", 0.0)  # mapeada (para que tenga tamaño) pero invisible

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.frame = ctk.CTkFrame(self.root, width=400, height=200)
        self.frame.pack_propagate(False)
        self.frame.pack()
        self.addCleanup(self.frame.destroy)

    def _settle(self):
        for _ in range(5):
            self.root.update()

    def test_wraps_to_the_container_and_keeps_the_cap_as_a_maximum(self):
        label = ctk.CTkLabel(self.frame, text="palabra " * 80, wraplength=900, justify="left")
        label.pack(anchor="w", padx=10)
        self._settle()
        fit_label_wrap(label)
        self._settle()
        self.assertLess(label.cget("wraplength"), 400)
        self.frame.configure(width=2000)
        self._settle()
        self.assertEqual(label.cget("wraplength"), 900)  # nunca mas ancho que el tope original

    def test_labels_without_wraplength_are_left_alone(self):
        label = ctk.CTkLabel(self.frame, text="corto")
        label.pack()
        fit_label_wrap(label)
        self.assertEqual(label.cget("wraplength"), 0)


if __name__ == "__main__":
    unittest.main()
