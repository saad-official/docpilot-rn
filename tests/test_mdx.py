from docpilot.ingest.mdx import (
    ReduceContext,
    js_object_fields,
    js_strings,
    parse_attributes,
    reduce_mdx,
)


def test_imports_and_exports_are_removed_including_multiline():
    body = (
        "import { A,\n  B } from '~/x';\nimport C from 'y';\nexport const meta = {\n  a: 1,\n};\n"
        "Text stays.\n"
    )
    assert reduce_mdx(body).strip() == "Text stays."


def test_terminal_object_keeps_only_npm_commands():
    body = (
        "<Terminal\n  cmd={{\n    npm: ['$ npx expo install expo-notifications'],\n"
        "    yarn: ['$ yarn expo install expo-notifications'],\n  }}\n/>\n"
    )
    out = reduce_mdx(body)
    assert "```sh\nnpx expo install expo-notifications\n```" in out
    assert "yarn" not in out


def test_terminal_array_keeps_every_command_and_comments():
    out = reduce_mdx("<Terminal cmd={['# Build', '$ eas build -p android', '']} />")
    assert "# Build\neas build -p android" in out


def test_tabs_become_labelled_text_and_code_is_verbatim():
    body = (
        '<Tabs>\n\n<Tab label="Expo Router">\n\nUse the root layout.\n\n```tsx app/_layout.tsx\n'
        "export default function Layout() {\n  return <Slot />; /* @info hidden note */\n}\n```\n\n"
        '</Tab>\n\n<Tab label="React Navigation">\n\nUse linking.\n\n</Tab>\n\n</Tabs>\n'
    )
    out = reduce_mdx(body)
    assert "**Expo Router:**" in out and "**React Navigation:**" in out
    assert "return <Slot />;" in out  # JSX inside code is not treated as a component
    assert "@info" not in out
    assert "```tsx app/_layout.tsx" in out
    assert "<Tab" not in out


def test_collapsible_and_requirement_keep_title_and_children():
    body = (
        '<Collapsible summary="Configure manually on iOS">\n\nAdd the key.\n\n</Collapsible>\n'
        '<Prerequisites>\n  <Requirement title="A device">\n    Use a phone.\n  </Requirement>\n'
        "</Prerequisites>\n"
    )
    out = reduce_mdx(body)
    assert "**Configure manually on iOS**" in out
    assert "Add the key." in out
    assert "**A device**" in out and "Use a phone." in out


def test_config_plugin_properties_become_a_table():
    body = """<ConfigPluginProperties
  properties={[
    {
      name: 'icon',
      platform: 'android',
      description:
        'Local path to an image. ' + 'Must be white.',
    },
    { name: 'mode', default: 'development', description: "Sets the APNs | environment" },
  ]}
/>"""
    out = reduce_mdx(body)
    assert "| Name | Default | Platform | Description |" in out
    assert "| `icon` | - | android | Local path to an image. Must be white. |" in out
    assert r"| `mode` | `development` | - | Sets the APNs \| environment |" in out


def test_api_section_and_install_section_use_the_package_name():
    out = reduce_mdx(
        '<APIInstallSection />\n\n<APISection packageName="expo-camera" apiName="Camera" />',
        ReduceContext(package_name="expo-camera"),
    )
    assert "npx expo install expo-camera" in out
    assert "API reference for `expo-camera` (`Camera`)" in out


def test_inline_components_and_entities_are_stripped_outside_code():
    out = reduce_mdx(
        "### Known issues&ensp;<PlatformTags platforms={['android']} />\n\n"
        "Use `<View>` here.<br />Done {' '}now.\n"
    )
    assert "### Known issues" in out and "PlatformTags" not in out
    assert "`<View>`" in out  # inline code is untouched
    assert "<br" not in out


def test_comments_and_admonitions():
    out = reduce_mdx("{/* hidden */}\n<!-- also\nhidden -->\n:::note Heads up\nBody.\n:::\n")
    assert "hidden" not in out
    assert "**Note:** Heads up" in out and "Body." in out


def test_partials_are_inlined():
    body = "import Linux from './_linux.md';\n\n<Linux />\n"
    partials = {"./_linux.md": "---\ntitle: x\n---\nInstall the JDK."}
    out = reduce_mdx(body, ReduceContext(resolve_partial=partials.get))
    assert "Install the JDK." in out


def test_js_helpers():
    assert js_strings("['a', \"b\", `c`]") == ["a", "b", "c"]
    assert parse_attributes('label="X" cmd={[1, {a: 2}]} hidden') == {
        "label": "X",
        "cmd": "[1, {a: 2}]",
        "hidden": "true",
    }
    assert js_object_fields("name: 'n', platforms: ['ios', 'android'], flag: true") == {
        "name": "n",
        "platforms": "ios, android",
        "flag": "true",
    }
