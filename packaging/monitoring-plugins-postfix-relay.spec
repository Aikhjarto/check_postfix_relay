#
# spec file for package monitoring-plugins-postfix-relay
#

Name:           monitoring-plugins-postfix-relay
Version:        0.1
Release:        0
Summary:        Nagios/Icinga plugin to check that Postfix can log in to its relays
License:        GPL-2.0-or-later
Group:          System/Monitoring
URL:            https://github.com/Aikhjarto/check_postfix_relay
Source:         %{url}/archive/refs/tags/v%{version}.tar.gz#/check_postfix_relay-%{version}.tar.gz
BuildRequires:  nagios-rpm-macros
BuildRequires:  python3
Requires:       postfix
Requires:       python3 >= 3.7
Recommends:     sudo
BuildArch:      noarch

%description
Nagios/Icinga plugin that checks that Postfix can log in to the relays it
sends through, written in Python 3 with the standard library only.

It tests the relayhost and every relay in sender_dependent_relayhost_maps:
connection, STARTTLS and SASL login with the credentials Postfix itself
would use (also by sender, smtp_sender_dependent_authentication), and
optionally MAIL FROM/RCPT TO without sending. Relays and logins come from
the Postfix configuration, so no password is needed in the monitoring
configuration. It needs root for the SASL password map, e.g. through a
NOPASSWD sudoers rule; see the README.

%prep
%autosetup -n check_postfix_relay-%{version}

%build

%install
install -D -m 0755 check_postfix_relay %{buildroot}%{nagios_plugindir}/check_postfix_relay

%check
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v

%files
%license LICENSE
%doc README.md sudoers.d/check_postfix_relay
%dir %{nagios_libdir}
%dir %{nagios_plugindir}
%{nagios_plugindir}/check_postfix_relay

%changelog
* Wed Oct 28 2026 Thomas Wagner <wagner-thomas@gmx.at>
- Initial package of check_postfix_relay 0.1
