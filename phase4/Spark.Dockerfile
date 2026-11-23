FROM eclipse-temurin:21-jdk-jammy AS java
FROM python:3.11-slim-bookworm AS storage
RUN pip install --no-cache-dir minio==7.2.15

FROM storage AS spark
COPY --from=java /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk
ENV PATH="${JAVA_HOME}/bin:${PATH}"
COPY requirements.txt /tmp/cloudmind-requirements.txt
RUN pip install --no-cache-dir -r /tmp/cloudmind-requirements.txt
ADD https://repo.maven.apache.org/maven2/org/apache/hadoop/hadoop-aws/3.4.1/hadoop-aws-3.4.1.jar /opt/s3a/hadoop-aws-3.4.1.jar
ADD https://repo.maven.apache.org/maven2/software/amazon/awssdk/bundle/2.24.6/bundle-2.24.6.jar /opt/s3a/bundle-2.24.6.jar
ENV CLOUDMIND_S3A_JARS=/opt/s3a
