// SPDX-License-Identifier: GPL-2.0-or-later
/* MediaTek DMA descriptor metadata DSA tag support */

#include <net/dst_metadata.h>

#include "tag.h"

#define MTK_OOB_NAME	"mtk-oob"

struct mtk_oob_tagger_data {
	unsigned int num_ports;
	struct metadata_dst *meta[];
};

static struct sk_buff *mtk_oob_xmit(struct sk_buff *skb,
				    struct net_device *dev)
{
	struct dsa_port *dp = dsa_user_to_port(dev);
	struct mtk_oob_tagger_data *data = dp->ds->tagger_data;

	skb_dst_drop(skb);
	skb_dst_set_noref(skb, &data->meta[dp->index]->dst);

	return skb;
}

static struct sk_buff *mtk_oob_rcv(struct sk_buff *skb,
				   struct net_device *dev)
{
	dev_err_ratelimited(&dev->dev,
			    "RX frame arrived without hardware-port metadata\n");
	return NULL;
}

static int mtk_oob_connect(struct dsa_switch *ds)
{
	struct mtk_oob_tagger_data *data;
	struct metadata_dst *md_dst;
	int port;

	data = kzalloc(struct_size(data, meta, ds->num_ports), GFP_KERNEL);
	if (!data)
		return -ENOMEM;

	data->num_ports = ds->num_ports;
	for (port = 0; port < ds->num_ports; port++) {
		md_dst = metadata_dst_alloc(0, METADATA_HW_PORT_MUX,
					    GFP_KERNEL);
		if (!md_dst)
			goto err_free;

		md_dst->u.port_info.port_id = port;
		data->meta[port] = md_dst;
	}

	ds->tagger_data = data;

	return 0;

err_free:
	while (port--)
		dst_release(&data->meta[port]->dst);
	kfree(data);

	return -ENOMEM;
}

static void mtk_oob_disconnect(struct dsa_switch *ds)
{
	struct mtk_oob_tagger_data *data = ds->tagger_data;
	int port;

	for (port = 0; port < data->num_ports; port++)
		dst_release(&data->meta[port]->dst);

	kfree(data);
	ds->tagger_data = NULL;
}

static const struct dsa_device_ops mtk_oob_ops = {
	.name		= MTK_OOB_NAME,
	.proto		= DSA_TAG_PROTO_MTK_OOB,
	.connect	= mtk_oob_connect,
	.disconnect	= mtk_oob_disconnect,
	.xmit		= mtk_oob_xmit,
	.rcv		= mtk_oob_rcv,
};

MODULE_DESCRIPTION("MediaTek DMA descriptor metadata DSA tag driver");
MODULE_LICENSE("GPL");
MODULE_ALIAS_DSA_TAG_DRIVER(DSA_TAG_PROTO_MTK_OOB, MTK_OOB_NAME);

module_dsa_tag_driver(mtk_oob_ops);
