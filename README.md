# check_postfix_relay

A Nagios/Icinga plugin that checks that Postfix can log in to the relays it
sends through, with the credentials Postfix itself would use. Python 3,
standard library only.

It reads the relays and logins from Postfix's own configuration, so nothing
has to be configured twice, and no password ever appears in the monitoring
configuration or on a command line.

## What it checks

For the `relayhost` and for every relay in `sender_dependent_relayhost_maps`:

1. connect, `EHLO` (as `smtp_helo_name`, or `myhostname`)
2. `STARTTLS`, unless `smtp_tls_security_level` is `none`; with
   `smtp_tls_wrappermode = yes` it connects with TLS right away (port 465).
   A relay without STARTTLS is critical if the security level requires TLS
   (`encrypt`, `secure`, `verify`, `dane`, ...).
3. `AUTH`, if `smtp_sasl_auth_enable = yes`, with the login Postfix would use:
   from `smtp_sasl_password_maps`, looked up by the sender first if
   `smtp_sender_dependent_authentication = yes`, then by the relay as
   written (`[mail.example.org]:587`), then without the port, then without
   the brackets
4. with `-r`, also `MAIL FROM` and `RCPT TO`, then `RSET`: no mail is sent.
   For the `relayhost` the sender is root rewritten by
   `sender_canonical_maps` (or `root@$myhostname`), for the other relays the
   sender of the map entry.

Each pair of relay and login is tested once. The maps must be types that
`postmap -s` can list (`lmdb`, `hash`, `btree`, `cdb`, `texthash`); regexp
and pcre tables can't be listed.

If the certificate of a relay can't be verified, the plugin reports a
warning and goes on unverified, as Postfix at `may` and `encrypt` does too.

## Usage

```sh
check_postfix_relay
check_postfix_relay -x user@example.org
check_postfix_relay -r postmaster@example.org -w 3 -c 10
```

```
OK - 3 relay login(s) ok | 'relayhost'=0.371s;5;15;0 'user@example.net'=0.442s;5;15;0 'other@example.org'=0.411s;5;15;0
OK relayhost: mail.example.org:587 answers in 0.4 s, TLS, login as system@example.org ok
OK user@example.net: smtp.example.net:587 answers in 0.4 s, TLS, login as user@example.net ok
OK other@example.org: mail.example.org:587 answers in 0.4 s, TLS, login as other@example.org ok
```

| Option | Meaning |
|---|---|
| `-r RCPT` | Also test `MAIL FROM`/`RCPT TO` with this recipient (then `RSET`, no mail is sent) |
| `-x SENDER` | Skip this sender of `sender_dependent_relayhost_maps`; repeatable |
| `-w SEC` | Warning if a relay takes this long, from connecting to `QUIT` (default: 5) |
| `-c SEC` | Critical if a relay takes this long (default: 15) |
| `-t SEC` | Timeout of each connection (default: 25) |
| `-V`, `--version` | Show the version |

### States

| State | When |
|---|---|
| OK | Every relay answers within `-w` and accepts its login |
| WARNING | A relay takes longer than `-w`, or its certificate can't be verified |
| CRITICAL | A relay is unreachable, has no STARTTLS or AUTH although needed, rejects the login, `MAIL FROM` or `RCPT TO`, or takes longer than `-c` |
| UNKNOWN | No credentials found for a relay (not run as root?), or a usage error |

The first line names the relays that are not OK; the following lines list
every relay with its state (long output).

### Performance data

The time of each relay, labelled with `relayhost` or the sender of the map
entry, in seconds with the `-w` and `-c` thresholds.

## Installation

```sh
install -D -m 755 check_postfix_relay /usr/lib/nagios/plugins/check_postfix_relay
```

The plugin calls `postconf` and `postmap`, so it runs on the Postfix host.
The SASL password map is readable by root only, so the monitoring user runs
the plugin through `sudo`; see [sudoers.d/check_postfix_relay](sudoers.d/check_postfix_relay):

```
nagios ALL=(root) NOPASSWD: /usr/lib/nagios/plugins/check_postfix_relay
```

```sh
install -m 440 sudoers.d/check_postfix_relay /etc/sudoers.d/check_postfix_relay
visudo -c
```

Use the name of your monitoring user (`nagios`, `icinga`, `naemon`).

### Naemon/Nagios via check_by_ssh

```
define command {
  command_name    ssh_postfix_relay
  command_line    $USER1$/check_by_ssh -u nagios -H $HOSTADDRESS$ -t 58 -C "sudo /usr/lib/nagios/plugins/check_postfix_relay -t 10 $ARG1$"
}

define service {
  service_description    Postfix: relayhost
  host_name              mailrelay
  use                    generic-service
  check_command          ssh_postfix_relay!-x user@example.org
  check_interval         360
  retry_interval         30
  notification_interval  360
}
```

Every check logs in to each relay; a few times a day is enough, and keeps
failed logins from piling up at a provider while a password is wrong.

## Why not check_smtp

`check_smtp` from the monitoring plugins can do STARTTLS and AUTH too, but it
takes the password as an argument: it would have to be in the monitoring
configuration, a second copy to keep up to date, and visible in the process
list of both machines when run through `check_by_ssh`. It also tests only the
relay you give it, not the one Postfix chooses for a sender. This plugin
takes relays and logins from Postfix, so a new entry in
`sender_dependent_relayhost_maps` is checked without touching the monitoring.

## Tests

```sh
python3 -m unittest -v
```

runs the plugin against a fake `postconf`/`postmap` and a fake SMTP relay.

## License

GPL-2.0-or-later. See [LICENSE](LICENSE).
