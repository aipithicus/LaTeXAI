use strict;
use warnings;
use Test::More tests => 1;
diag('qualification hang');
sleep 60;
ok(1, 'should not reach here under a job budget');
