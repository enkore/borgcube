import sphinx.application

from django import forms


def process_docstring(app, what, name, form: forms.Form, options, lines):
    if not isinstance(form, type):
        return lines
    if not issubclass(form, forms.Form):
        return lines

    for name, field in form.declared_fields.items():
        lines.append('`{name}` = `{mod}.{qn}`'.format(
            # Django docs has these aliased, hence forms.fields -> forms.
            name=name, mod=field.__class__.__module__.replace('forms.fields', 'forms'), qn=field.__class__.__qualname__))
        lines.append('')

    del form.declared_fields
    del form.base_fields
    del form.media

    return lines


def setup(app: sphinx.application.Sphinx):
    app.connect("autodoc-process-docstring", process_docstring)
