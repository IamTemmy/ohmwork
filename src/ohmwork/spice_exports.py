"""D19 transport metadata shared by CLI and web downloads; no circuit logic."""
from ohmwork.presenter import validate_output_name
from ohmwork.schematic import Layout
from ohmwork.spice import render_spice_example, render_spice_template


def build_spice_exports(layout: Layout) -> dict:
    """Use the displayed schematic's exact Layout; fail atomically on any error."""
    output = next(n.label for n in layout.nets if n.id == layout.output_net_id)
    name = validate_output_name(output, list(layout.var_order))
    return {
        "template": {
            "filename": f"ohmwork-{name}-template.sp",
            "text": render_spice_template(layout),
        },
        "example": {
            "filename": f"ohmwork-{name}-educational.cir",
            "text": render_spice_example(layout),
        },
    }
