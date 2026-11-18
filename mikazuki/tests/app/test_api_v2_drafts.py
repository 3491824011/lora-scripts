import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from mikazuki.app import api_v2
from mikazuki.compiler.models import ImportDraftRequest


class DraftImportApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_imports_toml_text(self) -> None:
        request = ImportDraftRequest(
            trainerId="moss_image.lora",
            toml="[training]\nmax_train_epochs = 1\n",
            name="demo",
        )

        response = await api_v2.import_draft(request)

        self.assertEqual([], response["errors"])
        self.assertEqual("demo", response["draft"]["name"])

    async def test_imports_toml_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "train.toml"
            source.write_text("[training]\nmax_train_epochs = 1\n", encoding="utf-8")
            request = ImportDraftRequest(trainerId="moss_image.lora", path=str(source))

            response = await api_v2.import_draft(request)

        self.assertEqual([], response["errors"])

    async def test_imports_external_dataset_config_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "dataset.toml").write_text(
                "[general]\ncaption_extension = '.txt'\n"
                "[[datasets]]\nresolution = [1024, 1024]\n"
                "[[datasets.subsets]]\nimage_dir = 'train/demo'\n",
                encoding="utf-8",
            )
            source = root / "train.toml"
            source.write_text("[dataset]\ndataset_config = 'dataset.toml'\n", encoding="utf-8")
            request = ImportDraftRequest(trainerId="moss_image.lora", path=str(source))

            response = await api_v2.import_draft(request)

        self.assertEqual([], response["errors"])
        self.assertEqual("train/demo", response["draft"]["dataset"]["root"])

    async def test_rejects_empty_toml(self) -> None:
        request = ImportDraftRequest(trainerId="moss_image.lora", toml=" ")

        with self.assertRaises(HTTPException) as raised:
            await api_v2.import_draft(request)

        self.assertEqual(400, raised.exception.status_code)

    async def test_rejects_unsupported_file_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "train.json"
            source.write_text("{}", encoding="utf-8")
            request = ImportDraftRequest(trainerId="moss_image.lora", path=str(source))

            with self.assertRaises(HTTPException) as raised:
                await api_v2.import_draft(request)

        self.assertEqual(400, raised.exception.status_code)


if __name__ == "__main__":
    unittest.main()
