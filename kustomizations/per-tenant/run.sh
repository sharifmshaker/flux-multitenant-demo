 echo 'substituted'; if [ 'substituted' = '$''{''PER_TENANT_SUBST''}' ]; then echo 1>&2 'no substitution applied?!'; exit 1; else echo 1>&2 'subst seems to have been applied ok'; sleep inf; fi
