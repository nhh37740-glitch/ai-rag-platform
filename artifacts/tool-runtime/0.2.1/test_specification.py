import importlib
import importlib.machinery
from pathlib import Path
import sys
import unittest

class Contract(unittest.TestCase):
    def test_import(self):
        artifact = Path(__file__).resolve().parent
        sys.path.insert(0, str(artifact))
        m = importlib.import_module('tool_runtime')
        module_path = Path(m.__file__).resolve()
        self.assertTrue(
            module_path.name.endswith(tuple(importlib.machinery.EXTENSION_SUFFIXES)),
            f'{m.__name__} loaded source instead of a compiled extension: {module_path}',
        )
        self.assertEqual(module_path.parent, (artifact / 'tool_runtime').resolve())
        self.assertEqual(getattr(m, '__version__', None), artifact.name)

if __name__ == '__main__':
    unittest.main()
