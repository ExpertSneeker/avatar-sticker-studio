# 商品详情

来源：https://open.agiso.com/document/#/aldsXhs/api/productDetail（2026-10-08 抓取的渲染文本）

商品详情

简要描述：  接口调用示例

￥高级
根据小红书商品Id，查询商品详情。

请求URL：

https://gw-api.agiso.com/aldsXhs/Product/Detail

请求方式：

POST

公共Header：

参数名	必选	类型	说明
Authorization
	
是
	
string
	
httpPost.addHeader("Authorization","Bearer "+ accessToken)


ApiVersion
	
是
	
string
	
httpPost.addHeader("ApiVersion", "1")


Content-Type
	
是
	
string
	
值必须为：application/x-www-form-urlencoded

公共参数：

参数名	必选	类型	说明
timestamp
	
是
	
Date
	
时间戳，例如：1468476350。API服务端允许客户端请求最大时间误差为10分钟。


sign
	
是
	
string
	
API输入参数签名结果,签名算法参照下面的介绍。

参数：

参数名	必选	类型	说明
item_id
	
是
	
String
	
小红书商品Id(因为历史原因,我们将sku当做商品,实际这个是Sku的Id,对应小红书接口:product.getDetailSkuList)

返回示例


  {
    "isSuccess": true,    // 是否成功
    "data": {
        "item": {
            "name": "测试商品，虚拟商品，勿拍，勿改",          // 商品标题
            "ename": "",                                    // 商品英文名
            "brandId": 0,                                   // 品牌ID
            "categoryId": "65f996e83e946300016b27e8",       // 末级商品类目ID
            "attributes": [
                {
                    "propertyId": "626902ed01b3b400010d5b67",    // 属性ID
                    "name": "是否带框",                           // 属性名
                    "valueId": "66264eb02c821c0001a3db57",        // 属性值ID
                    "value": "否",                                // 属性值，单选属性使用
                    "valueList": []                               // 属性值列表，多选属性填入列表
                },
                {
                    "propertyId": "626902ee01b3b400010d5b6d",     // 属性ID
                    "name": "是否限量",                            // 属性名
                    "valueId": "66264eb02c821c0001a3db57",        // 属性值ID
                    "value": "否",                                // 属性值，单选属性使用
                    "valueList": []                               // 属性值列表，多选属性填入列表
                },
                {
                    "propertyId": "626902ee01b3b400010d5ba7",     // 属性ID
                    "name": "作品尺寸",                            // 属性名
                    "value": "10mm*10mm",                         // 属性值，单选属性使用
                    "valueList": []                               // 属性值列表，多选属性填入列表
                },
                {
                    "propertyId": "626902ed01b3b400010d5b4d",     // 属性ID
                    "name": "创作年份",                            // 属性名
                    "value": "2025",                              // 属性值，单选属性使用
                    "valueList": []                               // 属性值列表，多选属性填入列表
                },
                {
                    "propertyId": "626902ee01b3b400010d5b70",     // 属性ID
                    "name": "题材",                               // 属性名
                    "value": "风景",                              // 属性值，单选属性使用
                    "valueList": [
                        {
                            "valueId": "66264ec22c821c0001a3e02d",    // 属性值ID,接口查不到需要的属性可不填
                            "value": "风景"                           // 属性值，接口查不到需要的属性可自行填写
                        }
                    ]
                },
                {
                    "propertyId": "626902ed01b3b400010d5b6a",     // 属性ID
                    "name": "是否签名",                            // 属性名
                    "valueId": "66264eb02c821c0001a3db57",        // 属性值ID，单选属性时必填
                    "value": "否",                                // 属性值，单选属性使用
                    "valueList": []                               // 属性值列表，多选属性填入列表
                }
            ],
            "shippingTemplateId": "64f196dee1f0f10001fd8bb1",    // 运费模板ID
            "shippingGrossWeight": 0,                            // 商品物流重量（克），当运费模版选择按重量计费时，该值必须大于0
            "variantIds": [                                      // 商品规格列表
                "5a60c42f69bd891ed8939bc2"
            ],    
            "images": [
                "http://qimg.xiaohongshu.com/arkgoods/1040g0o03111p5bu1mk8g5p7hi6f14q14ocupbo0"   // 商品主图
            ],    
            "videoUrl": "",                                       // 主图视频
            "articleNo": "",                                      // 商品货号
            "imageDescriptions": [
                "http://qimg.xiaohongshu.com/arkgoods/104100ao31bqrrtvr0s069sclc5qg0000000005t6t3hds"   // 图文描述
            ],    
            "transparentImage": "",                                 // 透明图
            "description": "",                                      // 商品描述
            "faq": [],                                              // 常见的问题
            "deliveryMode": 1,                                      // 物流模式,0：普通，1：支持无物流发货（限定类目支持，不支持的类目创建会报错）
            "freeReturn": 1,                                        // 是否支持7天无理由,1：支持，2：不支持，不传会按照规则给默认值，必须支持则支持，不必须则不支持
            "id": "67b6831c7b3de40001a9fb78",                       // spuId,创建时不填，删除更新必填
            "createTime": 1740014364000,                            // spu创建时间
            "updateTime": 1740014448000                             // spu更新时间
        },
        "sku": {
            "itemId": "67b6831c7b3de40001a9fb78",                   // 商品id
            "ipq": 1,                                               // 打包数
            "originalPrice": 100000,                                // 市场价，单位分
            "price": 99900,                                         // 售价，单位分，要求小于市场价，上限10w元，即10000000分 原来这个字段单位是元
            "stock": 100,                                           // 库存
            "logisticsPlanId": "64f58c46138fbd00012e23b8",          // 物流方案Id
            "whcode": "CPartner",                                   // 仓库号
            "priceType": 0,                                         // 是否包税，0：不包税；1：包税
            "erpCode": "",                                          // 商家编码
            "variants": [
                {
                    "id": "5a60c42f69bd891ed8939bc2",               // 规格ID(spl与spv规格根据common.getVariations区分，spl规格和spv规格集合需要与spu规格对齐)
                    "name": "款式",                                 // 规格名称
                    "value": "04款",                                // 规格值(通过common.getAttributeValues获取)，查不到则自行填写
                    "valueId": "662651af2c821c0001a453b1"           // 规格值ID(通过common.getAttributeValues获取)查不到可以不填
                }
            ],
            "deliveryTime": {
                "time": "48",                                       // 发货时间，相对时间(X)付款后X天内发货，绝对时间(YYYY/MM/DD)该天24点之前发货
                "type": "RELATIVE_TIME_NEW"                         // 发货时间类型，DEFAULT:不设置 RELATIVE_TIME:相对时间 ABSOLUTE_TIME:绝对时间
            },
            "specImage": "",                                        // 规格图
            "barcode": "XHS-32JY3DKV2Q68",                          // 商品条形码，创建特定品类必填，普通品类可不填
            "id": "67b6831c7b3de40001a9fb97",                       // skuId,仅更新删除返回使用
            "scSkucode": "XHS-32JY3DKV2Q68",                        // scSkuCode编号,小红书编码
            "logisticsName": "",                                    // 物流模式名
            "buyable": true,                                        // 是否在架上，仅用于返回
            "unionItemDetails": [],                                 // 组合商品子商品信息，仅返回使用
            "createTime": 1740014364000,                            // 商品创建时间，仅返回使用
            "updateTime": 1740014436000,                            // 商品更新时间，仅返回使用
            "name": "测试商品，虚拟商品，勿拍，勿改 04款",            // 商品名称，仅返回使用
            "isGift": false                                         // 是否是赠品
        }
    },
    "error_Code": 0,    // 错误码
    "error_Msg": ""    // 错误信息
}
    

备注

参考咸鱼：服务商闲鱼商品查询
