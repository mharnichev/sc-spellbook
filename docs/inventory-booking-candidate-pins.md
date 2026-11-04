# Inventory and booking candidate artifacts

Frontend source: `f21d77035890cdc91e76e129b4b0b08d52c9d0ac` (CI 41800319678).

- Public: `ghcr.io/mharnichev/sc-fe/admin-rewards-20261030-pr40@sha256:d78516a0f99c117a6f641b269ed2f91d16a0177a53bc58812fa210f7c91517ba`
- Admin: `ghcr.io/mharnichev/sc-fe/admin-rewards-20261030-pr40@sha256:ff5dbca00b8402637f2b5522cc91e0ecd7d4f61b7c751c48ac72b5e259e71420`

Backend source `41102378e9b24ec89df61ceccea4ef6d41e42509` passed CI 41800268803 and image smoke in 41802544142:

- Backend: `ghcr.io/mharnichev/sc-be/api-rewards-20261030-pr20@sha256:808a65df2475ac0696667113efc8c2d70bd4992f44ead8ed5e6e5f8972b3c40d`

Required schema: `0146_merge_inventory_booking`. Before promoting these pins, verify existing frontend compatibility with the published backend. Deploy backend first; retain paired backup and recovery gates. Do not downgrade on failure. Shop is unchanged.
