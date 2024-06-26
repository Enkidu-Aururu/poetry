from __future__ import annotations

from typing import TYPE_CHECKING

from poetry.utils.extras import get_extra_package_names


if TYPE_CHECKING:
    from packaging.utils import NormalizedName
    from poetry.core.packages.package import Package

    from poetry.installation.operations.operation import Operation


class Transaction:
    def __init__(
        self,
        current_packages: list[Package],
        result_packages: list[tuple[Package, int]],
        installed_packages: list[Package] | None = None,
        root_package: Package | None = None,
    ) -> None:
        self._current_packages = current_packages
        self._result_packages = result_packages

        if installed_packages is None:
            installed_packages = []

        self._installed_packages = installed_packages
        self._root_package = root_package

    def calculate_operations(
        self,
        with_uninstalls: bool = True,
        synchronize: bool = False,
        *,
        skip_directory: bool = False,
        extras: set[NormalizedName] | None = None,
    ) -> list[Operation]:
        from poetry.installation.operations import Install
        from poetry.installation.operations import Uninstall
        from poetry.installation.operations import Update

        operations: list[Operation] = []

        extra_packages: set[NormalizedName] = set()
        if extras is not None:
            assert self._root_package is not None
            extra_packages = get_extra_package_names(
                [package for package, _ in self._result_packages],
                {k: [d.name for d in v] for k, v in self._root_package.extras.items()},
                extras,
            )

        uninstalls: set[NormalizedName] = set()
        for result_package, priority in self._result_packages:
            installed = False
            is_unsolicited_extra = extras is not None and (
                result_package.optional and result_package.name not in extra_packages
            )

            for installed_package in self._installed_packages:
                if result_package.name == installed_package.name:
                    installed = True

                    # Extras that were not requested are always uninstalled.
                    if is_unsolicited_extra:
                        uninstalls.add(installed_package.name)
                        operations.append(Uninstall(installed_package))

                    # We have to perform an update if the version or another
                    # attribute of the package has changed (source type, url, ref, ...).
                    elif result_package.version != installed_package.version or (
                        (
                            # This has to be done because installed packages cannot
                            # have type "legacy". If a package with type "legacy"
                            # is installed, the installed package has no source_type.
                            # Thus, if installed_package has no source_type and
                            # the result_package has source_type "legacy" (negation of
                            # the following condition), update must not be performed.
                            # This quirk has the side effect that when switching
                            # from PyPI to legacy (or vice versa),
                            # no update is performed.
                            installed_package.source_type
                            or result_package.source_type != "legacy"
                        )
                        and not result_package.is_same_package_as(installed_package)
                    ):
                        operations.append(
                            Update(installed_package, result_package, priority=priority)
                        )
                    else:
                        operations.append(
                            Install(result_package).skip("Already installed")
                        )

                    break

            if not (
                installed
                or (skip_directory and result_package.source_type == "directory")
            ):
                op = Install(result_package, priority=priority)
                if is_unsolicited_extra:
                    op.skip("Not required")
                operations.append(op)

        if with_uninstalls:
            for current_package in self._current_packages:
                found = any(
                    current_package.name == result_package.name
                    for result_package, _ in self._result_packages
                )

                if not found:
                    for installed_package in self._installed_packages:
                        if installed_package.name == current_package.name:
                            uninstalls.add(installed_package.name)
                            operations.append(Uninstall(installed_package))

            if synchronize:
                result_package_names = {
                    result_package.name for result_package, _ in self._result_packages
                }
                # We preserve pip when not managed by poetry, this is done to avoid
                # externally managed virtual environments causing unnecessary removals.
                preserved_package_names = {"pip"} - result_package_names

                for installed_package in self._installed_packages:
                    if installed_package.name in uninstalls:
                        continue

                    if (
                        self._root_package
                        and installed_package.name == self._root_package.name
                    ):
                        continue

                    if installed_package.name in preserved_package_names:
                        continue

                    if installed_package.name not in result_package_names:
                        uninstalls.add(installed_package.name)
                        operations.append(Uninstall(installed_package))

        return sorted(
            operations,
            key=lambda o: (
                -o.priority,
                o.package.name,
                o.package.version,
            ),
        )
