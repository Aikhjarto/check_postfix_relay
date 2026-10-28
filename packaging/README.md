# Packaging

The files for the package `monitoring-plugins-postfix-relay` on the Open
Build Service: the RPM spec for openSUSE (and other RPM distributions), and
the `debian.*` files with the `.dsc` for Debian and Ubuntu, built by OBS's
debtransform from the release tarball of GitHub.

The spec downloads `v<version>.tar.gz` of the tag from GitHub; in the OBS
package, put the spec, the `debian.*` files, the `.dsc` and the tarball
(`check_postfix_relay-<version>.tar.gz`). After a release, update `Version`
and `%changelog` in the spec, `debian.changelog`, and `Version` and
`DEBTRANSFORM-TAR` in the `.dsc`.
