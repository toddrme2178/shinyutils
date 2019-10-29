"""argp.py: utilities for argparse."""

from argparse import ArgumentTypeError, HelpFormatter, FileType, SUPPRESS
import logging
import os
from pathlib import Path
import re
import shutil
import textwrap
from unittest.mock import patch

import crayons

from shinyutils.subcls import get_subclass_from_name, get_subclass_names


class LazyHelpFormatter(HelpFormatter):

    _CHOICE_SEP = "/"
    _DEFAULT_CHOICE_WRAP = "[]"
    _UNICODE_REPL = "\ufffc"  # placeholder character
    _PATTERN_HEXT = re.compile(r"\(.*?\)$", re.DOTALL)
    _PATTERN_DEFAULT = re.compile(r"(?<=default: ).+?(?=\))")
    _PATTERN_KEYWORD = re.compile(r"default|optional|required")
    _PATTERN_CHOICE = re.compile(
        fr"(?<=\{{|{_CHOICE_SEP}| )[^{_CHOICE_SEP}\b]+?(?=\}}|{_CHOICE_SEP}|\n)"
    )

    def _color_helper(self, s, color, isbold):
        # pylint: disable=no-self-use
        if isinstance(s, re.Match):
            s = s.group(0)
        color_fun = getattr(crayons, color)
        return str(color_fun(s, isbold))

    def _COLOR_KEYWORD(self, s):
        return self._color_helper(s, "green", isbold=False)

    def _COLOR_CHOICE(self, s):
        return self._color_helper(s, "blue", isbold=False)

    def _COLOR_DEFAULT(self, s):
        return self._color_helper(s, "blue", isbold=True)

    def _COLOR_METAVAR(self, s):
        return self._color_helper(s, "red", isbold=True)

    @property
    def _DUMMY_CMV(self):
        # empty colored metavar
        return self._COLOR_METAVAR("")

    @property
    def _HELP_WIDTH(self):
        basew = shutil.get_terminal_size()[0]
        return basew + len(self._DUMMY_CMV)

    def _format_action(self, action):
        if action.nargs == 0 and action.option_strings:
            # hack to fix length of option strings
            # when nargs=0, there's no metavar, or the extra color codes
            action.option_strings[0] += self._DUMMY_CMV

        # generate base format without help text
        help_ = action.help
        action.help = "\b"
        base_fmt = super()._format_action(action)

        # compute extra help text (choices, default etc.)
        if action.choices:
            choice_strs = list(map(str, action.choices))
            # replace separators in choices with placeholders to restore later
            choice_strs = [
                c.replace(self._CHOICE_SEP, self._UNICODE_REPL) for c in choice_strs
            ]
            # mark the default choice if present
            try:
                def_pos_in_choices = action.choices.index(action.default)
            except ValueError:
                def_pos_in_choices = -1
            else:
                if def_pos_in_choices != -1:
                    c = choice_strs[def_pos_in_choices]
                    wpref, wsuff = self._DEFAULT_CHOICE_WRAP
                    choice_strs[def_pos_in_choices] = f"{wpref}{c}{wsuff}"
            # combine all the choices
            hext = f"{{{self._CHOICE_SEP.join(choice_strs)}}}"
            if action.required and action.option_strings:
                # indicate optional arguments which are required
                hext = f"({hext} required)"
            elif def_pos_in_choices == -1 and action.option_strings:
                # mark as optional
                hext = f"({hext} optional)"
            else:
                hext = f"({hext})"
        elif not action.option_strings:
            # positional arguments can't be optional, don't have defaults,
            #   and are always required - so no extra text required
            hext = None
        elif action.required:
            hext = "(required)"
        elif action.default is None:
            hext = "(optional)"
        elif action.default != SUPPRESS:
            hext = f"(default: {action.default})"
        else:
            hext = None

        # combine 'base_fmt' with 'help_' and 'hext'
        fmt = base_fmt.strip("\n")
        if help_:
            fmt += " " + help_
        if hext:
            fmt += (" " if help_ or action.nargs != 0 else "") + hext

        # wrap the formatted text
        # indentation computation needs to take color codes into account
        #   and i'm not completely certain why this is correct
        indent = self._COLOR_METAVAR("\b\b") + " " * (
            len(base_fmt.strip("\n"))
            - len(self._DUMMY_CMV)
            - 1
            + self._indent_increment
        )
        fmt = textwrap.fill(fmt, width=self._HELP_WIDTH, subsequent_indent=indent)

        # add colors to 'hext' inside the formatted text
        fmt_hext_match = re.search(self._PATTERN_HEXT, fmt)
        if fmt_hext_match:
            fmt_hext = fmt_hext_match.group(0)
            # color default values
            fmt_hext_colored = re.sub(
                self._PATTERN_DEFAULT, self._COLOR_DEFAULT, fmt_hext
            )
            # color keywords
            fmt_hext_colored = re.sub(
                self._PATTERN_KEYWORD, self._COLOR_KEYWORD, fmt_hext_colored
            )

            # color choices
            def _sub_choice(m):
                c = m.group(0)
                nonlocal choice_strs, def_pos_in_choices
                if def_pos_in_choices != -1:
                    def_str = choice_strs[def_pos_in_choices]
                else:
                    def_str = None

                # check if the match is surrounded by the default marking wrapper
                pref, suff = "", ""
                if def_str and def_str.startswith(c):
                    pref = c[0]
                    c = c[1:]
                if def_str and def_str.endswith(c):
                    suff = c[-1]
                    c = c[:-1]

                if pref or suff:
                    sub = self._COLOR_DEFAULT(c)
                else:
                    sub = self._COLOR_CHOICE(c)

                return pref + sub + suff

            fmt_hext_colored = re.sub(
                self._PATTERN_CHOICE, _sub_choice, fmt_hext_colored
            )

            # replace the placeholders with separators
            fmt_hext_colored = fmt_hext_colored.replace(
                self._UNICODE_REPL, self._CHOICE_SEP
            )

            # replace hext in the formatted text with the new colored version
            fmt = fmt.replace(fmt_hext, fmt_hext_colored)

        return fmt + "\n"

    def _format_action_invocation(self, action):
        if action.option_strings and action.nargs != 0:
            # show action as -s/--long ARGS rather than -s ARGS, --long ARGS
            combined_opt_strings = self._CHOICE_SEP.join(action.option_strings)
            with patch.object(action, "option_strings", [combined_opt_strings]):
                return super()._format_action_invocation(action)

        with patch.object(  # format positional arguments same as optional
            action, "option_strings", action.option_strings or [action.dest]
        ):
            return super()._format_action_invocation(action)

    def _get_default_metavar_for_optional(self, action):
        if action.type:
            try:
                return action.type.__name__
            except AttributeError:
                return type(action.type).__name__
        return None

    def _get_default_metavar_for_positional(self, action):
        if action.type:
            try:
                return action.type.__name__
            except AttributeError:
                return type(action.type).__name__
        return None

    def _metavar_formatter(self, action, default_metavar):
        with patch.object(action, "choices", None):
            # don't put choices in the metavar
            base_formatter = super()._metavar_formatter(action, default_metavar)

        def color_wrapper(tuple_size):
            f = base_formatter(tuple_size)
            if not f:
                return f
            return (
                self._COLOR_METAVAR(" ".join(map(str, f))),
                *(("",) * (len(f) - 1)),  # collapse to single metavar
            )

        return color_wrapper

    def __init__(self, *args, **kwargs):
        kwargs["max_help_position"] = float("inf")
        kwargs["width"] = float("inf")
        super().__init__(*args, **kwargs)

    def add_usage(self, *args, **kwargs):
        pass

    def start_section(self, heading):
        if heading == "positional arguments":
            heading = "arguments"
        elif heading == "optional arguments":
            heading = "options"
        super().start_section(heading)


def comma_separated_ints(string):
    try:
        return list(map(int, string.split(",")))
    except:
        raise ArgumentTypeError(f"`{string}` is not a comma separated list of ints")


class InputFileType(FileType):
    def __init__(self, mode="r", **kwargs):
        if mode not in {"r", "rb"}:
            raise ValueError("mode should be 'r'/'rb'")
        super().__init__(mode, **kwargs)


class OutputFileType(FileType):
    def __init__(self, mode="w", **kwargs):
        if mode not in {"w", "wb"}:
            raise ValueError("mode should be 'w'/'wb'")
        super().__init__(mode, **kwargs)

    def __call__(self, string):
        file_dir = os.path.dirname(string)
        if file_dir and not os.path.exists(file_dir):
            logging.warning(f"no directory for {string}: trying to create")
            try:
                os.makedirs(file_dir)
            except Exception as e:
                raise ArgumentTypeError(f"could not create {file_dir}: {e}")
            logging.info(f"created {file_dir}")
        return super().__call__(string)


class InputDirectoryType:
    def __call__(self, string):
        if not os.path.exists(string):
            raise ArgumentTypeError(f"no such directory: {string}")
        return Path(string)


class OutputDirectoryType:
    def __call__(self, string):
        if not os.path.exists(string):
            logging.warning(f"{string} not found: trying to create")
            try:
                os.makedirs(string)
            except Exception as e:
                raise ArgumentTypeError(f"cound not create {string}: {e}")
            logging.info(f"created {string}")
        return Path(string)


class ClassType:
    def __init__(self, cls):
        self.cls = cls

    def __call__(self, string):
        try:
            return get_subclass_from_name(self.cls, string)
        except RuntimeError:
            choices = [f"'{c}'" for c in get_subclass_names(self.cls)]
            raise ArgumentTypeError(
                f"invalid choice: '{string}' " f"(choose from {', '.join(choices)})"
            )


class KeyValuePairsType:
    def __call__(self, string):
        out = dict()
        try:
            for kv in string.split(","):
                k, v = kv.split("=")
                try:
                    v = int(v)
                except ValueError:
                    try:
                        v = float(v)
                    except ValueError:
                        pass
                out[k] = v
        except Exception as e:
            raise ArgumentTypeError(e)
        return out
