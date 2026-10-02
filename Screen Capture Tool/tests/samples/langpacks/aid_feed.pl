#!/usr/bin/perl
# Nightly feed of aid payments to the county systems
use strict;
use DBI;
use Net::FTP;
my $dbh = DBI->connect("dbi:Oracle:SCHFINP", "aidfeed", "feedpw1") or die;
my $period = $ARGV[0];
sub build_file {
    my ($p) = @_;
    my $sth = $dbh->prepare("SELECT district_id, amount FROM aid_payment WHERE period = '$p'");
    $sth->execute();
    open(OUT, ">/data/aid/feed_$p.txt") or die;
    while (my @r = $sth->fetchrow_array) { print OUT join("|", @r), "\n"; }
    close(OUT);
}
build_file($period);
system("gzip /data/aid/feed_$period.txt");
my $ftp = Net::FTP->new("county-ftp.example.org");
$ftp->put("/data/aid/feed_$period.txt.gz");
