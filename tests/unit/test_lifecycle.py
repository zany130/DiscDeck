import unittest

from discdeck.lifecycle import Lifecycle


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_unload_and_uninstall_do_not_eject_or_delete(self) -> None:
        lifecycle = Lifecycle()
        lifecycle.tasks.append("observer")
        await lifecycle.main()
        self.assertEqual(lifecycle.phase, "main")
        await lifecycle.unload()
        self.assertEqual(lifecycle.phase, "unloaded")
        self.assertEqual(lifecycle.tasks, [])
        self.assertFalse(lifecycle.eject_called)
        self.assertFalse(lifecycle.user_data_deleted)
        await lifecycle.uninstall()
        self.assertEqual(lifecycle.phase, "uninstalled")
        self.assertFalse(lifecycle.eject_called)
        self.assertFalse(lifecycle.user_data_deleted)


if __name__ == "__main__":
    unittest.main()
