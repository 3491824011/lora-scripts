import unittest

from mikazuki.catalog import get_catalog_service
from mikazuki.compiler.importer import import_train_toml


class ImporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = get_catalog_service()
        cls.trainer = cls.catalog.get_trainer("moss_image.lora")
        assert cls.trainer is not None

    def test_imports_dataset_tables_and_common_training_params(self) -> None:
        text = """
[model]
pretrained_model_name_or_path = "models/demo.safetensors"

[network]
network_module = "networks.lora_generic"
network_dim = 16
network_alpha = 8

[training]
max_train_epochs = 1
seed = 42

[general]
caption_extension = ".txt"

[[datasets]]
resolution = [1024, 1024]
batch_size = 1
enable_bucket = true

[[datasets.subsets]]
image_dir = "train/demo"
num_repeats = 1
"""

        result = import_train_toml(self.trainer, text, base_name="demo")

        self.assertEqual(result.errors, [])
        self.assertEqual(result.draft["name"], "demo")
        self.assertEqual(result.draft["dataset"]["root"], "train/demo")
        self.assertEqual(result.draft["dataset"]["resolution"], [1024, 1024])
        self.assertEqual(result.draft["dataset"]["captionExtension"], ".txt")
        self.assertEqual(result.draft["modelAssets"]["pretrained_model_name_or_path"], "models/demo.safetensors")
        self.assertEqual(result.draft["params"]["network_dim"], 16)

    def test_imports_external_dataset_toml(self) -> None:
        train_text = """
[dataset]
dataset_config = "dataset.toml"
"""
        dataset_text = """
[general]
caption_extension = ".txt"

[[datasets]]
resolution = [1024, 1024]
batch_size = 1

[[datasets.subsets]]
image_dir = "train/demo"
num_repeats = 2
"""

        result = import_train_toml(self.trainer, train_text, dataset_text=dataset_text)

        self.assertEqual(result.errors, [])
        self.assertEqual(result.draft["dataset"]["root"], "train/demo")
        self.assertEqual(result.draft["dataset"]["numRepeats"], 2)
        self.assertEqual(result.draft["dataset"]["captionExtension"], ".txt")

    def test_invalid_toml_returns_a_validation_error(self) -> None:
        result = import_train_toml(self.trainer, "not = [valid")

        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].code, "import.toml.invalid")

    def test_unknown_section_key_is_reported_as_a_warning(self) -> None:
        text = """
[training]
not_a_real_parameter = 1
"""

        result = import_train_toml(self.trainer, text)

        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(result.warnings[0].code, "import.param.unknown")
        self.assertEqual(result.unknownCount, 1)


if __name__ == "__main__":
    unittest.main()
