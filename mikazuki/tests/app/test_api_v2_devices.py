import unittest
from unittest.mock import patch

from mikazuki.app import api_v2


class DevicesApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_gpus_uses_nvidia_smi_when_cuda_is_unavailable(self) -> None:
        fallback = [
            {
                "id": "0",
                "name": "NVIDIA GeForce RTX 4060 Ti",
                "vramTotal": 16 * 1024**3,
                "vramFree": 12 * 1024**3,
            }
        ]
        with (
            patch("torch.cuda.is_available", return_value=False),
            patch.object(api_v2, "_nvidia_smi_gpus", return_value=fallback),
        ):
            result = await api_v2.list_gpus()

        self.assertEqual(fallback, result["gpus"])
        self.assertIn("CUDA", result["error"])

    async def test_list_gpus_reports_torch_devices(self) -> None:
        class Props:
            total_memory = 16 * 1024**3

        with (
            patch("torch.cuda.is_available", return_value=True),
            patch("torch.cuda.device_count", return_value=1),
            patch("torch.cuda.get_device_properties", return_value=Props()),
            patch("torch.cuda.get_device_name", return_value="NVIDIA GeForce RTX 4060 Ti"),
            patch("torch.cuda.mem_get_info", return_value=(12 * 1024**3, 16 * 1024**3)),
        ):
            result = await api_v2.list_gpus()

        self.assertEqual(1, len(result["gpus"]))
        self.assertEqual("NVIDIA GeForce RTX 4060 Ti", result["gpus"][0]["name"])
        self.assertEqual(16 * 1024**3, result["gpus"][0]["vramTotal"])

    async def test_list_gpus_survives_mem_get_info_failure(self) -> None:
        class Props:
            total_memory = 16 * 1024**3

        with (
            patch("torch.cuda.is_available", return_value=True),
            patch("torch.cuda.device_count", return_value=1),
            patch("torch.cuda.get_device_properties", return_value=Props()),
            patch("torch.cuda.get_device_name", return_value="NVIDIA GeForce RTX 4060 Ti"),
            patch("torch.cuda.mem_get_info", side_effect=RuntimeError("driver query failed")),
        ):
            result = await api_v2.list_gpus()

        self.assertEqual(1, len(result["gpus"]))
        self.assertEqual(16 * 1024**3, result["gpus"][0]["vramTotal"])
        self.assertEqual(0, result["gpus"][0]["vramFree"])

    def test_nvidia_smi_output_is_parsed(self) -> None:
        output = "0, NVIDIA GeForce RTX 4060 Ti, 16384, 12000\n"
        with (
            patch("mikazuki.app.api_v2.shutil.which", return_value="C:/Windows/nvidia-smi.exe"),
            patch("mikazuki.app.api_v2.subprocess.check_output", return_value=output),
        ):
            gpus = api_v2._nvidia_smi_gpus()

        self.assertEqual(1, len(gpus))
        self.assertEqual("NVIDIA GeForce RTX 4060 Ti", gpus[0]["name"])
        self.assertEqual(16384 * 1024 * 1024, gpus[0]["vramTotal"])
        self.assertEqual(12000 * 1024 * 1024, gpus[0]["vramFree"])


if __name__ == "__main__":
    unittest.main()
