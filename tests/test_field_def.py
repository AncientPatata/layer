"""Tests for field definitions: metadata, descriptions, class/instance access, and explain()."""

from layer import field, layerclass, one_of, require


@layerclass
class MetaConfig:
    endpoint: str = field(
        str,
        cluster=[require],
        meta={"cli_option": "--endpoint", "envvar": "AK__Endpoint"},
        description="ArmoniK cluster endpoint URL",
    )


@layerclass
class DescConfig:
    endpoint: str = field(str, description="The cluster endpoint URL")
    port: int = field(int, default=5000, description="Port number")
    debug: bool = field(bool, default=False)


@layerclass
class ExplainConfig:
    endpoint: str = field(str, cluster=[require], description="Cluster URL")
    output: str = field(str, common=[one_of("json", "yaml")], default="json", description="Format")


class TestFieldDefMeta:
    def test_meta_dict_stored(self):
        fdef = MetaConfig._field_defs["endpoint"]
        assert fdef.meta["cli_option"] == "--endpoint"
        assert fdef.meta["envvar"] == "AK__Endpoint"

    def test_description_stored(self):
        assert MetaConfig._field_defs["endpoint"].description == "ArmoniK cluster endpoint URL"

    def test_accessible_without_instance(self):
        assert "endpoint" in MetaConfig._field_defs
        assert MetaConfig._field_defs["endpoint"].meta["cli_option"] == "--endpoint"


class TestFieldDefsAttribute:
    def test_available_on_class(self):
        @layerclass
        class C:
            port: int = field(int, default=5000)

        assert hasattr(C, "_field_defs")
        assert "port" in C._field_defs

    def test_available_on_instance(self):
        @layerclass
        class C:
            port: int = field(int, default=5000)

        assert "port" in C()._field_defs


class TestExplain:
    def test_descriptions_appear(self):
        c = DescConfig()
        info = c.explain()
        ep = next(i for i in info if i["field"] == "endpoint")
        assert ep["description"] == "The cluster endpoint URL"
        db = next(i for i in info if i["field"] == "debug")
        assert db["description"] is None

    def test_explain_structure(self):
        c = ExplainConfig()
        c.set("endpoint", "http://localhost", source="cli")
        info = c.explain()
        ep = next(i for i in info if i["field"] == "endpoint")
        assert ep["value"] == "http://localhost"
        assert ep["source"] == "cli"
        assert ep["type"] == "str"
        assert ep["description"] == "Cluster URL"
        assert "cluster" in ep["categories"]
