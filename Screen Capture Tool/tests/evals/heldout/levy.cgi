#!/usr/bin/perl
use strict;
use CGI;
use DBI;
my $q = CGI->new;
my $dbh = DBI->connect("dbi:ODBC:LEVYDB", "web", "levyweb");
sub show_levy {
    my ($d) = @_;
    my $sth = $dbh->prepare("SELECT amount FROM levy_cert WHERE district_id = ?");
    $sth->execute($d);
    print $q->header, "<p>", $sth->fetchrow_array, "</p>";
}
show_levy($q->param('d'));
