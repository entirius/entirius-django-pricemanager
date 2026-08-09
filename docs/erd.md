---
title: "Pricemanager: Database Diagrams"
description: "Auto-generated ER diagrams for the Pricemanager module."
sidebar:
  badge:
    text: "Auto-gen"
    variant: "note"
---

:::caution[Auto-generated]
These diagrams are auto-generated from Django model introspection.
Do not edit. Run `make erd` in entirius-docker to regenerate.
:::

## Core Pricing

```d2 layout=elk
CurrentPrice: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  product_id: int {constraint: foreign_key}
  product_parent_id: int {constraint: foreign_key}
  channel_id: int {constraint: foreign_key}
  country_id: int {constraint: foreign_key}
  currency_id: int {constraint: foreign_key}
  customer_representation_id: int {constraint: foreign_key}
  tax_rate_id: int {constraint: foreign_key}
}

PriceHistory: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  product_id: int {constraint: foreign_key}
  channel_id: int {constraint: foreign_key}
  country_id: int {constraint: foreign_key}
  currency_id: int {constraint: foreign_key}
  customer_representation_id: int {constraint: foreign_key}
  tax_rate_id: int {constraint: foreign_key}
  changed_by_id: int {constraint: foreign_key}
}

CurrentPriceAttribute: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  current_price_id: int {constraint: foreign_key}
  attr_id: int {constraint: foreign_key}
}

AttributeRepresentation: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "AttributeRepresentation (See products diagram)"
}

Channel: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "Channel (See channels diagram)"
}

Country: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "Country (External: django_regional)"
}

Currency: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "Currency (See products diagram)"
}

CustomerRepresentation: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "CustomerRepresentation (See products diagram)"
}

ProductRepresentation: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "ProductRepresentation (See products diagram)"
}

TaxRate: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "TaxRate (See tax diagram)"
}

User: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "User (External: auth)"
}



CurrentPrice.product_id -> ProductRepresentation.id: {style.stroke: "#484B57"}

CurrentPrice.product_parent_id -> ProductRepresentation.id: {style.stroke: "#484B57"}

CurrentPrice.channel_id -> Channel.id: {style.stroke: "#484B57"}

CurrentPrice.country_id -> Country.id: {style.stroke: "#484B57"}

CurrentPrice.currency_id -> Currency.id: {style.stroke: "#484B57"}

CurrentPrice.customer_representation_id -> CustomerRepresentation.id: {style.stroke: "#484B57"}

CurrentPrice.tax_rate_id -> TaxRate.id: {style.stroke: "#484B57"}

PriceHistory.product_id -> ProductRepresentation.id: {style.stroke: "#484B57"}

PriceHistory.channel_id -> Channel.id: {style.stroke: "#484B57"}

PriceHistory.country_id -> Country.id: {style.stroke: "#484B57"}

PriceHistory.currency_id -> Currency.id: {style.stroke: "#484B57"}

PriceHistory.customer_representation_id -> CustomerRepresentation.id: {style.stroke: "#484B57"}

PriceHistory.tax_rate_id -> TaxRate.id: {style.stroke: "#484B57"}

PriceHistory.changed_by_id -> User.id: {style.stroke: "#484B57"}

CurrentPriceAttribute.current_price_id -> CurrentPrice.id: {style.stroke: "#00ACC1"}

CurrentPriceAttribute.attr_id -> AttributeRepresentation.id: {style.stroke: "#484B57"}
```

## Tax Configuration

```d2 layout=elk
TaxClass: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  idx: varchar {constraint: unique}
  name: varchar
  source_file: varchar
}

TaxRate: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  tax_class_id: int {constraint: foreign_key}
  country_id: int {constraint: foreign_key}
  rate: decimal
}

Country: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "Country (External: django_regional)"
}



TaxRate.tax_class_id -> TaxClass.id: {style.stroke: "#00ACC1"}

TaxRate.country_id -> Country.id: {style.stroke: "#484B57"}
```

## Channels

```d2 layout=elk
Channel: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  default_country_id: int {constraint: foreign_key}
  idx: varchar
  name: varchar
  calculate_direction: int
}

SaleChannel: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  channel_id: int {constraint: foreign_key}
  country_id: int {constraint: foreign_key}
  customer_representation_id: int {constraint: foreign_key}
  idx: varchar
  name: varchar
  is_only_for_verified_user: bool
  price_source: varchar
}

Country: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "Country (External: django_regional)"
}

CustomerRepresentation: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "CustomerRepresentation (See products diagram)"
}



Channel.default_country_id -> Country.id: {style.stroke: "#484B57"}

Channel.id <-> Country.id: {style.stroke: "#484B57"}

SaleChannel.channel_id -> Channel.id: {style.stroke: "#00ACC1"}

SaleChannel.country_id -> Country.id: {style.stroke: "#484B57"}

SaleChannel.customer_representation_id -> CustomerRepresentation.id: {style.stroke: "#484B57"}
```

## Product & Attribute Representations

```d2 layout=elk
ProductRepresentation: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  tax_class_id: int {constraint: foreign_key}
  sku: varchar
}

AttributeRepresentation: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  tax_class_id: int {constraint: foreign_key}
  idx: varchar
}

CustomerRepresentation: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  uid: varchar
  user_email: varchar
}

Currency: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  code: varchar {constraint: unique}
  name: varchar
  sign: varchar
}

TaxClass: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "TaxClass (See tax diagram)"
}



ProductRepresentation.tax_class_id -> TaxClass.id: {style.stroke: "#484B57"}

AttributeRepresentation.tax_class_id -> TaxClass.id: {style.stroke: "#484B57"}
```

## Legacy (Deprecated)

```d2 layout=elk
PriceList: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  sale_channel_id: int {constraint: foreign_key}
  currency_id: int {constraint: foreign_key}
  country_id: int {constraint: foreign_key}
  name: varchar
  source_file: varchar
  status: int
}

Price: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  pricelist_id: int {constraint: foreign_key}
  product_id: int {constraint: foreign_key}
  product_parent_id: int {constraint: foreign_key}
  tax_rate_id: int {constraint: foreign_key}
  net_value: decimal
  gross_value: decimal
  special_net_value: decimal
}

PriceAttribute: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  price_id: int {constraint: foreign_key}
  attr_id: int {constraint: foreign_key}
}

AttributeRepresentation: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "AttributeRepresentation (See products diagram)"
}

Country: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "Country (External: django_regional)"
}

Currency: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "Currency (See products diagram)"
}

ProductRepresentation: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "ProductRepresentation (See products diagram)"
}

SaleChannel: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "SaleChannel (See channels diagram)"
}

TaxRate: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "TaxRate (See tax diagram)"
}



PriceList.sale_channel_id -> SaleChannel.id: {style.stroke: "#484B57"}

PriceList.currency_id -> Currency.id: {style.stroke: "#484B57"}

PriceList.country_id -> Country.id: {style.stroke: "#484B57"}

Price.pricelist_id -> PriceList.id: {style.stroke: "#00ACC1"}

Price.product_id -> ProductRepresentation.id: {style.stroke: "#484B57"}

Price.product_parent_id -> ProductRepresentation.id: {style.stroke: "#484B57"}

Price.tax_rate_id -> TaxRate.id: {style.stroke: "#484B57"}

PriceAttribute.price_id -> Price.id: {style.stroke: "#00ACC1"}

PriceAttribute.attr_id -> AttributeRepresentation.id: {style.stroke: "#484B57"}
```
