# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import csv

from django_pricemanager.models import TaxRate


def read_from_csv(tax_class, absolute_path: str | None = None):
    if absolute_path is not None:
        path = absolute_path
    else:
        path = tax_class.source_file.path
    with open(path) as f:
        reader = csv.reader(f)
        contents = []
        for line in reader:
            contents.append(line)

    name = contents[0][0]
    if name == tax_class.name:
        for line in contents[1:]:
            country_code = line[0]
            tax_rate = float(line[1])
            rate = TaxRate.objects.update_or_create(
                tax_class=tax_class, country=country_code, defaults={"rate": tax_rate}
            )
